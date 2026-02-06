from __future__ import annotations

import logging
from math import ceil

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_manager_menu
from app.handlers.filters import ManagerFilter
from app.keyboards.common import BACK_TEXT, build_inline_keyboard
from app.keyboards.manager import (
    MANAGER_MENU_HELP,
    MANAGER_MENU_ORGS,
    MANAGER_MENU_REGISTER_ORG,
    ORG_ACTION_RESET_PASSWORD,
    ORG_ACTION_STAFF,
    ORG_CREATE_BACK_TO_MENU,
    ORG_CREATE_CONFIRM,
    ORG_CREATE_OPEN_CARD,
    ORG_CREATE_OPEN_CARD_FULL,
    ORG_RESET_CONFIRM,
    manager_back_menu,
    manager_main_menu,
    org_create_confirm_menu,
    org_created_menu,
    org_exists_menu,
    org_reset_confirm_menu,
)
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


@router.message(F.text == MANAGER_MENU_REGISTER_ORG)
async def manager_register_org(message: Message, state: FSMContext) -> None:
    if not is_manager(message.from_user.id):
        return
    await state.clear()
    await state.set_state(OrgCreateStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=manager_back_menu())


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
    support_link = f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
    await message.answer(
        "Бот помогает регистрировать организации и продавцов.\n"
        f"Если возникли вопросы, напишите в {support_link}.",
        reply_markup=manager_back_menu(),
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
