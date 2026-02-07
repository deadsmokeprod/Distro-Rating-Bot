from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from math import ceil
import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import FSInputFile

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_manager_menu
from app.handlers.filters import ManagerFilter
from app.keyboards.common import BACK_TEXT, build_inline_keyboard, support_contact_line, support_inline_keyboard
from app.keyboards.manager import (
    MANAGER_MENU_HELP,
    MANAGER_MENU_ORGS,
    MANAGER_MENU_REGISTER_ORG,
    MANAGER_MENU_EXPORT_RATINGS,
    MANAGER_MENU_SYNC,
    MANAGER_SYNC_CURRENT_MONTH,
    MANAGER_SYNC_CUSTOM_RANGE,
    ORG_ACTION_RESET_PASSWORD,
    ORG_ACTION_STAFF,
    ORG_CREATE_BACK_TO_MENU,
    ORG_CREATE_CONFIRM,
    ORG_CREATE_OPEN_CARD,
    ORG_CREATE_OPEN_CARD_FULL,
    ORG_RESET_CONFIRM,
    manager_back_menu,
    manager_main_menu,
    manager_sync_menu,
    org_create_confirm_menu,
    org_created_menu,
    org_exists_menu,
    org_reset_confirm_menu,
)
from app.services.onec_client import OnecClientError
from app.services.turnover_sync import current_month_range, moscow_today, sync_turnover
from app.services.ratings import month_str, moscow_today as moscow_today_ratings
from app.services.ratings_export import build_ratings_excel
from app.utils.security import generate_password, hash_password
from app.utils.validators import validate_inn, validate_org_name

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(ManagerFilter())
router.callback_query.filter(ManagerFilter())

PAGE_SIZE = 10


class OrgCreateStates(StatesGroup):
    inn = State()
    name = State()
    confirm = State()


class ManagerSyncStates(StatesGroup):
    choose_period = State()
    custom_range = State()


class ManagerExportStates(StatesGroup):
    period = State()


async def _send_error(message: Message) -> None:
    await message.answer("Произошла ошибка, попробуйте позже.", reply_markup=manager_back_menu())


def _org_list_keyboard(
    orgs: list[dict], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for org in orgs:
        text = f"{org['name']} — {org['inn']}"
        buttons.append((text, f"org_open:{org['id']}:{page}"))

    if page > 0:
        buttons.append(("◀️", f"org_page:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("▶️", f"org_page:{page + 1}"))
    buttons.append(("⬅️ Назад", "org_back_menu"))
    return build_inline_keyboard(buttons)


def _org_card_keyboard(org_id: int, back_page: int | None) -> InlineKeyboardMarkup:
    buttons = [
        (ORG_ACTION_STAFF, f"org_staff:{org_id}:0"),
        (ORG_ACTION_RESET_PASSWORD, f"org_reset:{org_id}"),
    ]
    if back_page is None:
        buttons.append(("⬅️ Назад", "org_back_menu"))
    else:
        buttons.append(("⬅️ Назад", f"org_page:{back_page}"))
    return build_inline_keyboard(buttons)


def _org_reset_confirm_keyboard(org_id: int) -> InlineKeyboardMarkup:
    buttons = [
        (ORG_RESET_CONFIRM, f"org_reset_confirm:{org_id}"),
        ("⬅️ Назад", f"org_open:{org_id}:0"),
    ]
    return build_inline_keyboard(buttons)


def _org_staff_keyboard(org_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    if page > 0:
        buttons.append(("◀️", f"org_staff:{org_id}:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("▶️", f"org_staff:{org_id}:{page + 1}"))
    buttons.append(("⬅️ Назад", f"org_open:{org_id}:0"))
    return build_inline_keyboard(buttons)


def _parse_custom_range(text: str) -> tuple[date, date] | None:
    pattern = r"^\s*(\d{2})(\d{2})(\d{4})\s*по\s*(\d{2})(\d{2})(\d{4})\s*$"
    match = re.match(pattern, text)
    if not match:
        return None
    day1, month1, year1, day2, month2, year2 = match.groups()
    try:
        start = datetime(int(year1), int(month1), int(day1)).date()
        end = datetime(int(year2), int(month2), int(day2)).date()
    except ValueError:
        return None
    if start > end:
        return None
    if (end - start) > timedelta(days=60):
        return None
    return start, end


def _parse_month_range(text: str) -> tuple[str, str] | None:
    pattern = r"^\s*с\s*(\d{2})\s*(\d{4})\s*по\s*(\d{2})\s*(\d{4})\s*$"
    match = re.match(pattern, text)
    if not match:
        return None
    m1, y1, m2, y2 = match.groups()
    try:
        start = date(int(y1), int(m1), 1)
        end = date(int(y2), int(m2), 1)
    except ValueError:
        return None
    if start > end:
        return None
    return month_str(start), month_str(end)


@router.message(F.text == MANAGER_MENU_REGISTER_ORG)
async def manager_register_org(message: Message, state: FSMContext) -> None:
    if not is_manager(message.from_user.id):
        return
    await state.clear()
    await state.set_state(OrgCreateStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=manager_back_menu())


@router.message(F.text == MANAGER_MENU_EXPORT_RATINGS)
async def manager_export_ratings_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ManagerExportStates.period)
    await message.answer(
        'Введите период в формате: "с ММ ГГГГ по ММ ГГГГ".\n'
        "Например: с 01 2026 по 03 2026",
        reply_markup=manager_back_menu(),
    )


@router.message(ManagerExportStates.period, F.text == BACK_TEXT)
async def manager_export_ratings_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_manager_menu(message)


@router.message(ManagerExportStates.period)
async def manager_export_ratings_run(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Введите период или нажмите ⬅️ Назад.")
        return
    parsed = _parse_month_range(message.text)
    if not parsed:
        await message.answer(
            'Неверный формат. Ожидаю: "с ММ ГГГГ по ММ ГГГГ".',
            reply_markup=manager_back_menu(),
        )
        return
    start_month, end_month = parsed
    await state.clear()
    config = get_config()
    current_month_label = f"{moscow_today_ratings().month:02d} {moscow_today_ratings().year}"
    try:
        path = await build_ratings_excel(
            config.db_path, start_month, end_month, current_month_label
        )
        filename = f"ratings_{start_month}_to_{end_month}.xlsx"
        await message.answer_document(
            FSInputFile(path, filename=filename),
            caption="Выгрузка рейтингов",
        )
    except Exception:
        logger.exception("Failed to export ratings")
        await message.answer("Не удалось сформировать выгрузку.", reply_markup=manager_main_menu())


@router.message(F.text == MANAGER_MENU_SYNC)
async def manager_sync_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ManagerSyncStates.choose_period)
    await message.answer("Выберите период для обновления базы.", reply_markup=manager_sync_menu())


@router.message(ManagerSyncStates.choose_period, F.text == BACK_TEXT)
async def manager_sync_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_manager_menu(message)


@router.message(ManagerSyncStates.choose_period, F.text == MANAGER_SYNC_CURRENT_MONTH)
async def manager_sync_current_month(message: Message, state: FSMContext) -> None:
    config = get_config()
    await state.clear()
    start, end = current_month_range(moscow_today())
    try:
        fetched, upserted = await sync_turnover(config, start, end)
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=message.from_user.id,
            actor_role="manager",
            action="SYNC_TURNOVER",
            payload={
                "mode": "current_month",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "fetched": fetched,
                "upserted": upserted,
            },
        )
        await message.answer(
            "Обновление завершено.\n"
            f"Период: {start.isoformat()} — {end.isoformat()}\n"
            f"Получено строк: {fetched}\n"
            f"Записано/обновлено: {upserted}",
            reply_markup=manager_main_menu(),
        )
    except OnecClientError as exc:
        await message.answer(f"Ошибка 1С: {exc}", reply_markup=manager_main_menu())
    except Exception:
        logger.exception("Failed to sync turnover (current month)")
        await message.answer("Ошибка обновления базы.", reply_markup=manager_main_menu())


@router.message(ManagerSyncStates.choose_period, F.text == MANAGER_SYNC_CUSTOM_RANGE)
async def manager_sync_custom_range_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ManagerSyncStates.custom_range)
    await message.answer(
        "Введите период в формате: ДДММГГГГ по ДДММГГГГ.\n"
        "Например: 01012026 по 31012026",
        reply_markup=manager_back_menu(),
    )


@router.message(ManagerSyncStates.custom_range, F.text == BACK_TEXT)
async def manager_sync_custom_back(message: Message, state: FSMContext) -> None:
    await state.set_state(ManagerSyncStates.choose_period)
    await message.answer("Выберите период для обновления базы.", reply_markup=manager_sync_menu())


@router.message(ManagerSyncStates.custom_range)
async def manager_sync_custom_range(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Введите период или нажмите ⬅️ Назад.")
        return
    parsed = _parse_custom_range(message.text)
    if not parsed:
        await message.answer(
            "Неверный формат или период больше 60 дней.\n"
            "Ожидаю: ДДММГГГГ по ДДММГГГГ.",
            reply_markup=manager_back_menu(),
        )
        return
    start, end = parsed
    config = get_config()
    await state.clear()
    try:
        fetched, upserted = await sync_turnover(config, start, end)
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=message.from_user.id,
            actor_role="manager",
            action="SYNC_TURNOVER",
            payload={
                "mode": "custom_range",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "fetched": fetched,
                "upserted": upserted,
            },
        )
        await message.answer(
            "Обновление завершено.\n"
            f"Период: {start.isoformat()} — {end.isoformat()}\n"
            f"Получено строк: {fetched}\n"
            f"Записано/обновлено: {upserted}",
            reply_markup=manager_main_menu(),
        )
    except OnecClientError as exc:
        await message.answer(f"Ошибка 1С: {exc}", reply_markup=manager_main_menu())
    except Exception:
        logger.exception("Failed to sync turnover (custom range)")
        await message.answer("Ошибка обновления базы.", reply_markup=manager_main_menu())


@router.message(OrgCreateStates.inn, F.text == BACK_TEXT)
async def manager_org_inn_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_manager_menu(message)


@router.message(OrgCreateStates.inn)
async def manager_org_inn_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ИНН или нажмите ⬅️ Назад.")
        return
    inn = message.text.strip()
    if not validate_inn(inn):
        await message.answer("ИНН должен содержать 10 или 12 цифр", reply_markup=manager_back_menu())
        return

    config = get_config()
    try:
        existing = await sqlite.get_org_by_inn(config.db_path, inn)
        if existing:
            if int(existing["created_by_manager_id"]) == message.from_user.id:
                await state.clear()
                await state.update_data(existing_org_id=int(existing["id"]))
                await message.answer(
                    "Организация уже зарегистрирована вами.", reply_markup=org_exists_menu()
                )
                return
            await state.clear()
            await message.answer("Организация уже зарегистрирована.", reply_markup=manager_back_menu())
            return

        await state.update_data(inn=inn)
        await state.set_state(OrgCreateStates.name)
        await message.answer("Введите наименование организации.", reply_markup=manager_back_menu())
    except Exception:
        logger.exception("Failed to handle org inn input")
        await _send_error(message)


@router.message(OrgCreateStates.name, F.text == BACK_TEXT)
async def manager_org_name_back(message: Message, state: FSMContext) -> None:
    await state.set_state(OrgCreateStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=manager_back_menu())


@router.message(OrgCreateStates.name)
async def manager_org_name_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите наименование или нажмите ⬅️ Назад.")
        return
    name = message.text.strip()
    if not validate_org_name(name):
        await message.answer(
            "Наименование должно быть от 2 до 200 символов.", reply_markup=manager_back_menu()
        )
        return
    data = await state.get_data()
    inn = data.get("inn")
    await state.update_data(name=name)
    await state.set_state(OrgCreateStates.confirm)
    await message.answer(
        f"Проверьте данные:\nИНН: {inn}\nНаименование: {name}\nСоздать организацию?",
        reply_markup=org_create_confirm_menu(),
    )


@router.message(OrgCreateStates.confirm, F.text == BACK_TEXT)
async def manager_org_confirm_back(message: Message, state: FSMContext) -> None:
    await state.set_state(OrgCreateStates.name)
    await message.answer("Введите наименование организации.", reply_markup=manager_back_menu())


@router.message(OrgCreateStates.confirm, F.text == ORG_CREATE_CONFIRM)
async def manager_org_confirm_create(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    inn = data.get("inn")
    name = data.get("name")
    if not inn or not name:
        await state.clear()
        await show_manager_menu(message)
        return

    config = get_config()
    try:
        password_plain = generate_password()
        password_hash = hash_password(password_plain)
        org_id = await sqlite.create_org(
            config.db_path,
            inn=inn,
            name=name,
            password_hash=password_hash,
            created_by_manager_id=message.from_user.id,
        )
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=message.from_user.id,
            actor_role="manager",
            action="ORG_CREATE",
            payload={"org_id": org_id, "inn": inn},
        )
        await state.clear()
        await state.update_data(existing_org_id=org_id)
        await message.answer(
            "Организация создана.\n"
            f"ИНН: {inn}\n"
            f"Наименование: {name}\n"
            f"Пароль для регистрации продавцов: {password_plain}\n"
            "Сохраните пароль сейчас. Восстановить нельзя, можно только сбросить и выдать новый.",
            reply_markup=org_created_menu(),
        )
    except Exception:
        logger.exception("Failed to create org")
        await _send_error(message)


@router.message(OrgCreateStates.confirm)
async def manager_org_confirm_fallback(message: Message) -> None:
    await message.answer("Пожалуйста, нажмите ✅ Создать или ⬅️ Назад.")


@router.message(F.text == ORG_CREATE_OPEN_CARD)
@router.message(F.text == ORG_CREATE_OPEN_CARD_FULL)
async def manager_open_card_from_message(message: Message, state: FSMContext) -> None:
    if not is_manager(message.from_user.id):
        return
    data = await state.get_data()
    org_id = data.get("existing_org_id")
    if not org_id:
        await show_manager_menu(message)
        return
    await _send_org_card(message, message.from_user.id, org_id, back_page=None)


@router.message(F.text == ORG_CREATE_BACK_TO_MENU)
async def manager_back_to_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_manager_menu(message)


@router.message(F.text == MANAGER_MENU_ORGS)
async def manager_org_list(message: Message) -> None:
    if not is_manager(message.from_user.id):
        return
    await _send_org_list(message, page=0)


@router.callback_query(F.data.startswith("org_page"))
async def manager_org_list_page(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    page = int(callback.data.split(":")[1])
    await _send_org_list(callback.message, page=page, edit=True)
    await callback.answer()


@router.callback_query(F.data == "org_back_menu")
async def manager_org_back_menu(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Вы вошли как Менеджер.", reply_markup=manager_main_menu())
    await callback.answer()


async def _send_org_list(message: Message, page: int, edit: bool = False) -> None:
    config = get_config()
    total = await sqlite.count_orgs_by_manager(config.db_path, message.from_user.id)
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    orgs = await sqlite.list_orgs_by_manager(
        config.db_path, message.from_user.id, PAGE_SIZE, page * PAGE_SIZE
    )
    keyboard = _org_list_keyboard(orgs, page, total_pages)
    text = "Ваши организации:" if total else "У вас пока нет организаций."
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def _send_org_card(
    message: Message, user_id: int, org_id: int, back_page: int | None
) -> None:
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, org_id)
    if not org or int(org["created_by_manager_id"]) != user_id:
        await message.answer("Организация не найдена.", reply_markup=manager_main_menu())
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=user_id,
        actor_role="manager",
        action="VIEW_ORG",
        payload={"org_id": org_id},
    )
    count = await sqlite.count_sellers_by_org(config.db_path, org_id)
    text = (
        "Организация:\n"
        f"ИНН: {org['inn']}\n"
        f"Наименование: {org['name']}\n"
        f"Сотрудников зарегистрировано: {count}"
    )
    keyboard = _org_card_keyboard(org_id, back_page)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("org_open"))
async def manager_org_open(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    _, org_id, page = callback.data.split(":")
    await _send_org_card(callback.message, callback.from_user.id, int(org_id), back_page=int(page))
    await callback.answer()


@router.callback_query(F.data.startswith("org_staff"))
async def manager_org_staff(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    _, org_id, page = callback.data.split(":")
    org_id = int(org_id)
    page = int(page)
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, org_id)
    if not org or int(org["created_by_manager_id"]) != callback.from_user.id:
        await callback.message.answer("Организация не найдена.", reply_markup=manager_main_menu())
        await callback.answer()
        return
    total = await sqlite.count_sellers_by_org(config.db_path, org_id)
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    sellers = await sqlite.list_sellers_by_org(
        config.db_path, org_id, PAGE_SIZE, page * PAGE_SIZE
    )
    if sellers:
        lines = [
            f"{row['tg_user_id']} — {row['registered_at']}" for row in sellers
        ]
        text = "Сотрудники:\n" + "\n".join(lines)
    else:
        text = "Сотрудники не зарегистрированы."
    keyboard = _org_staff_keyboard(org_id, page, total_pages)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("org_reset:"))
async def manager_org_reset(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    _, org_id = callback.data.split(":")
    await callback.message.edit_text(
        "Сбросить пароль? Старый перестанет работать.",
        reply_markup=_org_reset_confirm_keyboard(int(org_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("org_reset_confirm:"))
async def manager_org_reset_confirm(callback: CallbackQuery) -> None:
    if not is_manager(callback.from_user.id):
        await callback.answer()
        return
    _, org_id = callback.data.split(":")
    org_id_int = int(org_id)
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, org_id_int)
    if not org or int(org["created_by_manager_id"]) != callback.from_user.id:
        await callback.message.answer("Организация не найдена.", reply_markup=manager_main_menu())
        await callback.answer()
        return
    password_plain = generate_password()
    password_hash = hash_password(password_plain)
    await sqlite.update_org_password(config.db_path, org_id_int, password_hash)
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=callback.from_user.id,
        actor_role="manager",
        action="ORG_PASSWORD_RESET",
        payload={"org_id": org_id_int},
    )
    await callback.message.edit_text(
        f"Новый пароль: {password_plain}",
        reply_markup=build_inline_keyboard([(BACK_TEXT, f"org_open:{org_id_int}:0")]),
    )
    await callback.answer()


@router.message(F.text == MANAGER_MENU_HELP)
async def manager_help(message: Message) -> None:
    if not is_manager(message.from_user.id):
        return
    config = get_config()
    await message.answer(
        "Бот помогает регистрировать организации и продавцов.\n"
        "Если возникли вопросы — напишите в техподдержку."
        + support_contact_line(config.support_username),
        reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
    )


@router.message(F.text == BACK_TEXT)
async def manager_back(message: Message) -> None:
    if not is_manager(message.from_user.id):
        return
    await show_manager_menu(message)


@router.message()
async def manager_fallback(message: Message) -> None:
    if not is_manager(message.from_user.id):
        return
    await message.answer("Пожалуйста, выберите пункт меню.", reply_markup=manager_main_menu())
