from __future__ import annotations

import logging
import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_seller_menu, show_seller_start
from app.handlers.filters import NonManagerFilter
from app.keyboards.common import (
    BACK_TEXT,
    build_inline_keyboard,
    support_contact_line,
    support_inline_keyboard,
)
from app.keyboards.seller import (
    SELLER_COMPANY_NO,
    SELLER_COMPANY_YES,
    SELLER_MENU_HELP,
    SELLER_MENU_GLOBAL_RATING,
    SELLER_MENU_PROFILE,
    SELLER_MENU_COMPANY_RATING,
    SELLER_MENU_SALES,
    SELLER_RETRY,
    SELLER_SUPPORT,
    seller_back_menu,
    seller_main_menu,
    seller_retry_menu,
    seller_support_menu,
    seller_start_menu,
)
from app.utils.security import verify_password
from app.utils.time import format_iso_human, now_utc_iso
from app.utils.validators import validate_inn
from app.services.ratings import (
    current_month_rankings,
    get_all_time_for_user,
    get_monthly_snapshot_for_user,
    moscow_today,
    previous_month,
    recalc_all_time_ratings,
)

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(NonManagerFilter())
router.callback_query.filter(NonManagerFilter())


class SellerRegisterStates(StatesGroup):
    inn = State()
    password = State()
    full_name = State()


SALES_PAGE_SIZE = 10


async def _send_error(message: Message) -> None:
    await message.answer("Произошла ошибка, попробуйте позже.", reply_markup=seller_back_menu())


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_sale_button_text(
    period: str, nomenclature: str, volume_goods: float, buyer_inn: str, buyer_name: str
) -> str:
    period_short = period.split("T")[0] if "T" in period else period
    volume_text = f"{volume_goods:g}"
    buyer_name_short = _shorten(buyer_name, 24)
    text = f"{period_short} | {volume_text} | {buyer_inn} | {buyer_name_short}"
    return _shorten(text, 64)


def _sales_list_keyboard(rows: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        buttons.append(
            (
                _format_sale_button_text(
                    row["period"],
                    row["nomenclature"],
                    row["volume_goods"],
                    row["buyer_inn"],
                    row["buyer_name"],
                ),
                f"sale_pick:{row['id']}:{page}",
            )
        )
    if page > 0:
        buttons.append(("⬅️ Назад", f"sale_page:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("➡️ Вперёд", f"sale_page:{page + 1}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _format_name(full_name: str, tg_user_id: int) -> str:
    name = full_name.strip()
    if not name:
        name = f"ID {tg_user_id}"
    return _escape_html(name)


def _build_rating_window(rows: list, current_id: int) -> list:
    if not rows:
        return []
    idx = next((i for i, r in enumerate(rows) if r.tg_user_id == current_id), None)
    if idx is None:
        return rows[:10]
    start = max(0, idx - 4)
    end = start + 10
    if end > len(rows):
        end = len(rows)
        start = max(0, end - 10)
    return rows[start:end]


def _render_rating_list(
    title: str, rows: list, current_id: int, use_company_rank: bool
) -> str:
    if not rows:
        return f"{title}\nНет данных."
    window = _build_rating_window(rows, current_id)
    lines = [title, "Место | Рейтинг | ФИО"]
    for r in window:
        rank = r.company_rank if use_company_rank else r.global_rank
        name = _format_name(r.full_name, r.tg_user_id)
        line = f"{rank} | {r.total_volume:g} | {name}"
        if r.tg_user_id == current_id:
            line = f"<b>{line}</b>"
        lines.append(line)
    return "\n".join(lines)


def _sale_confirm_keyboard(turnover_id: int, page: int) -> InlineKeyboardMarkup:
    buttons = [
        ("✅ Да", f"sale_confirm:{turnover_id}:{page}"),
        ("❌ Нет", f"sale_page:{page}"),
    ]
    return build_inline_keyboard(buttons)


async def _get_seller_org_inn(message: Message, tg_user_id: int) -> str | None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if not user:
        await show_seller_start(message)
        return None
    org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
    if not org:
        await show_seller_start(message)
        return None
    return str(org["inn"])


async def _render_sales_list(
    message: Message,
    seller_inn: str,
    page: int,
    note: str | None = None,
    edit: bool = False,
) -> None:
    config = get_config()
    total = await sqlite.count_unclaimed_turnover(config.db_path, seller_inn)
    if total == 0:
        text = "Нет доступных продаж для фиксации."
        if note:
            text = f"{note}\n\n{text}"
        await message.answer(text, reply_markup=seller_main_menu())
        return
    total_pages = max(1, math.ceil(total / SALES_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_unclaimed_turnover(
        config.db_path, seller_inn, SALES_PAGE_SIZE, page * SALES_PAGE_SIZE
    )
    rows_dict = [dict(row) for row in rows]
    header = (
        "Выберите продажу для фиксации:\n"
        "Период, ОбъемТоваров, ПокупательИНН, ПокупательНаименование"
    )
    if note:
        header = f"{note}\n\n{header}"
    if edit:
        await message.edit_text(
            header,
            reply_markup=_sales_list_keyboard(rows_dict, page, total_pages),
        )
    else:
        await message.answer(
            header,
            reply_markup=_sales_list_keyboard(rows_dict, page, total_pages),
        )


async def _process_registration(
    message: Message, state: FSMContext, inn: str, password: str
) -> None:
    config = get_config()
    try:
        org = await sqlite.get_org_by_inn(config.db_path, inn)
        if not org or not verify_password(password, org["password_hash"]):
            await message.answer(
                "Данные неверные.\n"
                "Проверьте ИНН и пароль. Если пароль не подходит — обратитесь в техподдержку."
                + support_contact_line(config.support_username),
                reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
            )
            return
        await state.set_state(SellerRegisterStates.full_name)
        await state.update_data(org_id=int(org["id"]), inn=inn)
        await message.answer("Введите ваше ФИО полностью.", reply_markup=seller_back_menu())
    except Exception:
        logger.exception("Failed to register seller")
        await _send_error(message)


async def _handle_company_yes(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await state.clear()
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


async def _handle_company_no(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    await state.clear()
    config = get_config()
    await message.answer(
        "Для регистрации компании обратитесь в техподдержку."
        + support_contact_line(config.support_username),
        reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
    )


@router.message(F.text.in_({SELLER_COMPANY_YES, "Да", "ДА", "да"}))
async def seller_register_start(message: Message, state: FSMContext) -> None:
    await _handle_company_yes(message, state)


@router.message(F.text.in_({SELLER_COMPANY_NO, "Нет", "НЕТ", "нет"}))
async def seller_company_no(message: Message, state: FSMContext) -> None:
    await _handle_company_no(message, state)


@router.message(SellerRegisterStates.inn, F.text == BACK_TEXT)
async def seller_register_inn_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_seller_start(message)


@router.message(SellerRegisterStates.inn)
async def seller_register_inn_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ИНН или нажмите ⬅️ Назад.")
        return
    inn = message.text.strip()
    if not validate_inn(inn):
        await message.answer("ИНН должен содержать 10 или 12 цифр", reply_markup=seller_back_menu())
        return
    config = get_config()
    org = await sqlite.get_org_by_inn(config.db_path, inn)
    if not org:
        await message.answer(
            "Организация не найдена.\n"
            "Проверьте ИНН или обратитесь в техподдержку для регистрации организации."
            + support_contact_line(config.support_username),
            reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
        )
        return
    await state.update_data(inn=inn)
    await state.set_state(SellerRegisterStates.password)
    await message.answer("Введите пароль организации.", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.password, F.text == BACK_TEXT)
async def seller_register_password_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.password)
async def seller_register_password_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите пароль или нажмите ⬅️ Назад.")
        return
    password = message.text.strip()
    data = await state.get_data()
    inn = data.get("inn")
    if not inn:
        await state.set_state(SellerRegisterStates.inn)
        await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())
        return
    await _process_registration(message, state, inn, password)


@router.message(SellerRegisterStates.full_name, F.text == BACK_TEXT)
async def seller_register_full_name_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.password)
    await message.answer("Введите пароль организации.", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.full_name)
async def seller_register_full_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ФИО или нажмите ⬅️ Назад.")
        return
    full_name = " ".join(message.text.strip().split())
    if len(full_name) < 5:
        await message.answer("ФИО слишком короткое. Введите полностью.", reply_markup=seller_back_menu())
        return
    data = await state.get_data()
    org_id = data.get("org_id")
    inn = data.get("inn")
    if not org_id:
        await state.clear()
        await show_seller_start(message)
        return
    config = get_config()
    registered_at = now_utc_iso()
    await sqlite.create_user(
        config.db_path,
        tg_user_id=message.from_user.id,
        org_id=int(org_id),
        registered_at=registered_at,
        last_seen_at=registered_at,
        full_name=full_name,
    )
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role="seller",
        action="SELLER_REGISTER",
        payload={"org_id": int(org_id), "inn": inn, "full_name": full_name},
    )
    await state.clear()
    await message.answer("Регистрация завершена ✅")
    await show_seller_menu(message)


@router.message(F.text == SELLER_RETRY)
async def seller_retry(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(F.text == SELLER_SUPPORT)
async def seller_support(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    await message.answer(
        "Контакт поддержки: нажмите ссылку ниже, чтобы написать в чат."
        + support_contact_line(config.support_username),
        reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
    )


@router.message(F.text == SELLER_MENU_PROFILE)
async def seller_profile(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await sqlite.update_last_seen(config.db_path, message.from_user.id)
    registered_at = format_iso_human(user["registered_at"])
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role="seller",
        action="VIEW_PROFILE",
        payload=None,
    )
    # Recalculate all-time ratings to keep profile up-to-date
    await recalc_all_time_ratings(config.db_path)
    all_time = await get_all_time_for_user(config.db_path, message.from_user.id) or {
        "total_volume": 0,
        "global_rank": 0,
        "company_rank": 0,
    }
    prev_month = previous_month(moscow_today())
    prev_snapshot = await get_monthly_snapshot_for_user(
        config.db_path, prev_month, message.from_user.id
    ) or {"total_volume": 0, "global_rank": 0, "company_rank": 0}

    await message.answer(
        "Профиль:\n"
        f"ID: {message.from_user.id}\n"
        f"Дата регистрации: {registered_at}\n\n"
        "Мой рейтинг за всё время: "
        f"{all_time['total_volume']} (в прошлом месяце было {prev_snapshot['total_volume']})\n"
        "Место в мировом рейтинге: "
        f"{all_time['global_rank']} (в прошлом месяце было {prev_snapshot['global_rank']})\n"
        "Место в рейтинге компании: "
        f"{all_time['company_rank']} (в прошлом месяце было {prev_snapshot['company_rank']})",
        reply_markup=seller_back_menu(),
    )


@router.message(F.text == SELLER_MENU_HELP)
async def seller_help(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    await message.answer(
        "Бот помогает зарегистрировать продавцов через ИНН и пароль.\n"
        "Если возникли сложности — напишите в техподдержку."
        + support_contact_line(config.support_username),
        reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
    )


@router.message(F.text == SELLER_MENU_SALES)
async def seller_sales_menu(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    seller_inn = await _get_seller_org_inn(message, message.from_user.id)
    if not seller_inn:
        return
    await _render_sales_list(message, seller_inn, page=0)


@router.message(F.text == SELLER_MENU_GLOBAL_RATING)
async def seller_global_rating(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    rows = await current_month_rankings(config.db_path)
    text = _render_rating_list(
        "Мировой рейтинг этого месяца", rows, message.from_user.id, use_company_rank=False
    )
    await message.answer(text, reply_markup=seller_back_menu())


@router.message(F.text == SELLER_MENU_COMPANY_RATING)
async def seller_company_rating(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    org_id = int(user["org_id"])
    rows = [r for r in await current_month_rankings(config.db_path) if r.org_id == org_id]
    rows = sorted(rows, key=lambda r: r.company_rank)
    text = _render_rating_list(
        "Рейтинг компании за этот месяц", rows, message.from_user.id, use_company_rank=True
    )
    await message.answer(text, reply_markup=seller_back_menu())


@router.callback_query(F.data == "sale_back_menu")
async def seller_sales_back_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await show_seller_menu(callback.message)


@router.callback_query(F.data.startswith("sale_page:"))
async def seller_sales_page(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 2:
        return
    try:
        page = int(parts[1])
    except ValueError:
        return
    seller_inn = await _get_seller_org_inn(callback.message, callback.from_user.id)
    if not seller_inn:
        return
    await _render_sales_list(callback.message, seller_inn, page=page, edit=True)


@router.callback_query(F.data.startswith("sale_pick:"))
async def seller_sales_pick(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    try:
        turnover_id = int(parts[1])
        page = int(parts[2])
    except ValueError:
        return
    config = get_config()
    seller_inn = await _get_seller_org_inn(callback.message, callback.from_user.id)
    if not seller_inn:
        return
    row = await sqlite.get_turnover_by_id(config.db_path, turnover_id)
    if not row or str(row["seller_inn"]) != seller_inn:
        await _render_sales_list(callback.message, seller_inn, page=page, edit=True)
        return
    if await sqlite.is_turnover_claimed(config.db_path, turnover_id):
        await _render_sales_list(callback.message, seller_inn, page=page, edit=True)
        return
    details = (
        f"Период: {row['period']}\n"
        f"Номенклатура: {row['nomenclature']}\n"
        f"ОбъемТоваров: {row['volume_goods']}\n"
        f"ПокупательИНН: {row['buyer_inn']}\n"
        f"Покупатель: {row['buyer_name']}\n\n"
        "Хотите подтвердить продажу?"
    )
    await callback.message.edit_text(details, reply_markup=_sale_confirm_keyboard(turnover_id, page))


@router.callback_query(F.data.startswith("sale_confirm:"))
async def seller_sales_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    try:
        turnover_id = int(parts[1])
        page = int(parts[2])
    except ValueError:
        return
    config = get_config()
    seller_inn = await _get_seller_org_inn(callback.message, callback.from_user.id)
    if not seller_inn:
        return
    row = await sqlite.get_turnover_by_id(config.db_path, turnover_id)
    if not row or str(row["seller_inn"]) != seller_inn:
        await _render_sales_list(callback.message, seller_inn, page=page, edit=True)
        return
    if await sqlite.is_turnover_claimed(config.db_path, turnover_id):
        await _render_sales_list(callback.message, seller_inn, page=page, edit=True)
        return
    try:
        await sqlite.claim_turnover(config.db_path, turnover_id, callback.from_user.id)
        await recalc_all_time_ratings(config.db_path)
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=callback.from_user.id,
            actor_role="seller",
            action="CLAIM_TURNOVER",
            payload={"turnover_id": turnover_id},
        )
        await _render_sales_list(
            callback.message,
            seller_inn,
            page=page,
            note="Продажа успешно зафиксирована за вами.",
            edit=True,
        )
    except Exception:
        logger.exception("Failed to claim turnover")
        await _render_sales_list(
            callback.message,
            seller_inn,
            page=page,
            note="Не удалось зафиксировать продажу.",
            edit=True,
        )


@router.message(F.text == BACK_TEXT)
async def seller_back(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await show_seller_start(message)


@router.message()
async def seller_fallback(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await message.answer("Пожалуйста, выберите пункт меню.", reply_markup=seller_main_menu())
    else:
        text = (message.text or "").strip().lower()
        normalized = text.replace("✅", "").replace("❌", "").strip()
        if normalized == "да":
            await _handle_company_yes(message, state)
            return
        if normalized == "нет":
            await _handle_company_no(message, state)
            return
        await message.answer("Пожалуйста, выберите «Да» или «Нет».", reply_markup=seller_start_menu())
