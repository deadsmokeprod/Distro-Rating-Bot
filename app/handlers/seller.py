from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import FSInputFile

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_seller_menu, show_seller_start
from app.handlers.filters import NonManagerFilter, PrivateChatFilter
from app.keyboards.common import (
    BACK_TEXT,
    build_inline_keyboard,
    support_contact_line,
    support_inline_keyboard,
)
from app.keyboards.seller import (
    SELLER_FIRE_ACTIVE,
    SELLER_FIRE_FIRED,
    SELLER_MENU_HELP,
    SELLER_MENU_MY_STAFF,
    SELLER_MENU_DISPUTE,
    SELLER_MENU_DISPUTE_MODERATE,
    SELLER_MENU_FINANCE,
    SELLER_MENU_FIRE_STAFF,
    SELLER_MENU_GOALS,
    SELLER_MENU_PROFILE,
    SELLER_MENU_REQUISITES,
    SELLER_MENU_COMPANY_RATING,
    SELLER_MENU_RULES,
    SELLER_MENU_SALES,
    SELLER_ROLE_ROP,
    SELLER_ROLE_SELLER,
    SELLER_START_REGISTER,
    SELLER_SUPPORT,
    seller_back_menu,
    seller_main_menu,
    seller_profile_menu,
    seller_role_menu,
    seller_start_menu,
)
from app.utils.security import verify_password
from app.utils.time import format_iso_human, now_utc_iso
from app.utils.validators import validate_inn
from app.utils.validators import validate_card_requisites_line
from app.utils.rate_limit import is_rate_limited
from app.services.ratings import (
    current_month_rankings,
    get_all_time_for_user,
    get_monthly_snapshot_for_user,
    moscow_today,
    previous_month,
    recalc_all_time_ratings,
)
from app.services.challenges import get_current_challenge, update_challenge_progress
from app.services.leagues import compute_league
from app.services.goals import render_personal_goals_text, sync_claim_goals
from app.services.staff_export import build_staff_sales_excel

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(NonManagerFilter())
router.callback_query.filter(NonManagerFilter())
router.message.filter(PrivateChatFilter())
router.callback_query.filter(PrivateChatFilter())


class SellerRegisterStates(StatesGroup):
    inn = State()
    role = State()
    password = State()
    full_name = State()
    nickname = State()


class RequisitesStates(StatesGroup):
    wait_text = State()


class WithdrawalStates(StatesGroup):
    wait_new_requisites = State()
    wait_amount = State()
    wait_confirm = State()


SALES_PAGE_SIZE = 10
DISPUTE_LIST_PAGE_SIZE = 8


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
    window_size = max(1, get_config().rating_window_size)
    idx = next((i for i, r in enumerate(rows) if r.tg_user_id == current_id), None)
    if idx is None:
        return rows[:window_size]
    left = window_size // 2
    start = max(0, idx - left)
    end = start + window_size
    if end > len(rows):
        end = len(rows)
        start = max(0, end - window_size)
    return rows[start:end]


def _render_rating_list(
    title: str,
    rows: list,
    current_id: int,
    use_company_rank: bool,
    league_map: dict[int, str] | None = None,
) -> str:
    if not rows:
        return f"{title}\nНет данных."
    window = _build_rating_window(rows, current_id)
    lines = [title, "Место | Рейтинг | ФИО | Лига"]
    for r in window:
        rank = r.company_rank if use_company_rank else r.global_rank
        name = _format_name(r.full_name, r.tg_user_id)
        league_suffix = ""
        if league_map and r.tg_user_id in league_map:
            league_suffix = f" ({league_map[r.tg_user_id]})"
        line = f"{rank} | {r.total_volume:g} | {name}{league_suffix}"
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


async def _get_seller_org_inns(message: Message, tg_user_id: int) -> list[str] | None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if not user:
        await show_seller_start(message)
        return None
    if str(user["status"]) != "active":
        org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
        inn = org["inn"] if org else "-"
        name = org["name"] if org else "Неизвестная организация"
        await message.answer(
            f"Вы уволены из компании {inn} {name}.\n"
            "Нажмите «📝 Регистрация в компании», чтобы зарегистрироваться снова.",
            reply_markup=seller_start_menu(),
        )
        return None
    inns = await sqlite.list_org_inns_by_group(config.db_path, int(user["company_group_id"]))
    if not inns:
        await show_seller_start(message)
        return None
    return inns


async def _render_sales_list(
    message: Message,
    seller_inns: list[str],
    page: int,
    note: str | None = None,
    edit: bool = False,
) -> None:
    config = get_config()
    launch_date_iso = config.bot_launch_date.isoformat()
    total = await sqlite.count_unclaimed_turnover_by_inns(
        config.db_path, seller_inns, launch_date_iso=launch_date_iso
    )
    if total == 0:
        text = "Нет доступных продаж для фиксации."
        if note:
            text = f"{note}\n\n{text}"
        await message.answer(text, reply_markup=seller_main_menu())
        return
    total_pages = max(1, math.ceil(total / SALES_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_unclaimed_turnover_by_inns(
        config.db_path,
        seller_inns,
        SALES_PAGE_SIZE,
        page * SALES_PAGE_SIZE,
        launch_date_iso=launch_date_iso,
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
    message: Message, state: FSMContext, inn: str, role: str, password: str
) -> None:
    config = get_config()
    try:
        org = await sqlite.get_org_by_inn(config.db_path, inn)
        if not org:
            await message.answer("Организация не найдена.", reply_markup=seller_back_menu())
            return
        password_hash = org["seller_password_hash"] if role == "seller" else org["rop_password_hash"]
        if not verify_password(password, password_hash):
            await message.answer(
                "Данные неверные.\n"
                "Проверьте ИНН и пароль. Если пароль не подходит — обратитесь в техподдержку."
                + support_contact_line(config.support_username),
                reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
            )
            return
        if await sqlite.has_active_registration_in_other_org(
            config.db_path, message.from_user.id, int(org["id"])
        ):
            await message.answer(
                "У вас уже есть активная регистрация в другой компании.\n"
                "Для перехода сначала нужно увольнение в текущей компании.",
                reply_markup=seller_start_menu(),
            )
            return
        current = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
        if (
            current
            and str(current["status"]) == "active"
            and int(current["org_id"]) == int(org["id"])
            and str(current["role"]) != role
        ):
            await message.answer(
                "Смена роли через повторную регистрацию недоступна. "
                "Обратитесь к менеджеру компании.",
                reply_markup=seller_start_menu(),
            )
            return
        if role == "rop":
            current_same_rop = (
                current
                and str(current["status"]) == "active"
                and str(current["role"]) == "rop"
                and int(current["org_id"]) == int(org["id"])
            )
            if not current_same_rop:
                rop_count = await sqlite.count_active_rops_by_org(config.db_path, int(org["id"]))
                if rop_count >= config.rop_limit_per_org:
                    await message.answer(
                        f"Достигнут лимит РОП для организации ({config.rop_limit_per_org}).",
                        reply_markup=seller_back_menu(),
                    )
                    return
        await state.set_state(SellerRegisterStates.full_name)
        await state.update_data(
            org_id=int(org["id"]),
            company_group_id=int(org["company_group_id"]),
            inn=inn,
            role=role,
        )
        await message.answer("Введите ваше ФИО полностью.", reply_markup=seller_back_menu())
    except Exception:
        logger.exception("Failed to register seller")
        await _send_error(message)


async def _handle_company_yes(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user and str(user["status"]) == "active":
        await show_seller_menu(message, message.from_user.id)
        return
    await state.clear()
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(F.text == SELLER_START_REGISTER)
async def seller_register_start(message: Message, state: FSMContext) -> None:
    await _handle_company_yes(message, state)


@router.message(SellerRegisterStates.inn, F.text == BACK_TEXT)
async def seller_register_inn_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_seller_start(message)


@router.message(SellerRegisterStates.inn)
async def seller_register_inn_input(message: Message, state: FSMContext) -> None:
    if is_rate_limited(f"reg_inn:{message.from_user.id}", limit=20, window_sec=60):
        await message.answer("Слишком много попыток. Подождите немного и попробуйте снова.")
        return
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
    await state.update_data(
        inn=inn,
        org_id=int(org["id"]),
        company_group_id=int(org["company_group_id"]),
    )
    await state.set_state(SellerRegisterStates.role)
    await message.answer("Выберите должность:", reply_markup=seller_role_menu())


@router.message(SellerRegisterStates.role, F.text == BACK_TEXT)
async def seller_register_role_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.role)
async def seller_register_role_input(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text not in {SELLER_ROLE_SELLER, SELLER_ROLE_ROP}:
        await message.answer("Выберите должность кнопкой ниже.", reply_markup=seller_role_menu())
        return
    role = "seller" if text == SELLER_ROLE_SELLER else "rop"
    await state.update_data(role=role)
    await state.set_state(SellerRegisterStates.password)
    await message.answer(
        f"Введите пароль для роли {text}.",
        reply_markup=seller_back_menu(),
    )


@router.message(SellerRegisterStates.password, F.text == BACK_TEXT)
async def seller_register_password_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.role)
    await message.answer("Выберите должность:", reply_markup=seller_role_menu())


@router.message(SellerRegisterStates.password)
async def seller_register_password_input(message: Message, state: FSMContext) -> None:
    if is_rate_limited(f"reg_pwd:{message.from_user.id}", limit=8, window_sec=60):
        await message.answer("Слишком много попыток ввода пароля. Подождите 1 минуту.")
        return
    if not message.text:
        await message.answer("Пожалуйста, введите пароль или нажмите ⬅️ Назад.")
        return
    password = message.text.strip()
    data = await state.get_data()
    inn = data.get("inn")
    role = data.get("role")
    if not inn or role not in {"seller", "rop"}:
        await state.set_state(SellerRegisterStates.inn)
        await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())
        return
    await _process_registration(message, state, inn, role, password)


@router.message(SellerRegisterStates.full_name, F.text == BACK_TEXT)
async def seller_register_full_name_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.password)
    await message.answer("Введите пароль организации для выбранной роли.", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.full_name)
async def seller_register_full_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ФИО или нажмите ⬅️ Назад.")
        return
    full_name = " ".join(message.text.strip().split())
    if len(full_name) < 5:
        await message.answer("ФИО слишком короткое. Введите полностью.", reply_markup=seller_back_menu())
        return
    await state.update_data(full_name=full_name)
    await state.set_state(SellerRegisterStates.nickname)
    await message.answer("Введите никнейм (уникален в компании).", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.nickname, F.text == BACK_TEXT)
async def seller_register_nickname_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.full_name)
    await message.answer("Введите ваше ФИО полностью.", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.nickname)
async def seller_register_nickname(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите никнейм или нажмите ⬅️ Назад.")
        return
    nickname = " ".join(message.text.strip().split())
    if len(nickname) < 2 or len(nickname) > 32:
        await message.answer("Никнейм должен быть длиной от 2 до 32 символов.", reply_markup=seller_back_menu())
        return
    data = await state.get_data()
    org_id = data.get("org_id")
    inn = data.get("inn")
    company_group_id = data.get("company_group_id")
    role = data.get("role")
    full_name = data.get("full_name")
    if not org_id or not company_group_id or role not in {"seller", "rop"} or not full_name:
        await state.clear()
        await show_seller_start(message)
        return
    config = get_config()
    current_user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    same_user_same_nick = (
        current_user
        and str(current_user["status"]) == "active"
        and int(current_user["company_group_id"]) == int(company_group_id)
        and str(current_user["nickname"]).lower() == nickname.lower()
    )
    if not same_user_same_nick and await sqlite.is_nickname_taken(
        config.db_path, int(company_group_id), nickname
    ):
        await message.answer(
            "Такой никнейм уже занят в компании. Введите другой.",
            reply_markup=seller_back_menu(),
        )
        return
    registered_at = now_utc_iso()
    await sqlite.create_user(
        config.db_path,
        tg_user_id=message.from_user.id,
        org_id=int(org_id),
        company_group_id=int(company_group_id),
        role=role,
        nickname=nickname,
        status="active",
        registered_at=registered_at,
        last_seen_at=registered_at,
        full_name=full_name,
    )
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role=role,
        action="USER_REGISTER",
        payload={
            "org_id": int(org_id),
            "inn": inn,
            "full_name": full_name,
            "nickname": nickname,
            "role": role,
        },
    )
    await state.clear()
    await message.answer("Регистрация завершена ✅")
    await show_seller_menu(message)


@router.message(F.text == "🔁 Попробовать снова")
async def seller_retry(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user and str(user["status"]) == "active":
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


@router.message(F.text == SELLER_MENU_RULES)
async def seller_rules(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    rules_path = Path(config.rules_file_path)
    if not rules_path.exists() or not rules_path.is_file():
        await message.answer(
            "Файл с правилами пока недоступен. Обратитесь в техподдержку."
            + support_contact_line(config.support_username),
            reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
        )
        return
    await message.answer_document(
        FSInputFile(rules_path),
        caption="Правила и рекомендации.",
    )


def _claim_title(row: dict) -> str:
    period = str(row["period"])[:10]
    volume = float(row["volume_goods"])
    buyer_inn = str(row["buyer_inn"])
    return _shorten(f"{period} | {volume:g} | {buyer_inn}", 64)


def _available_disputes_keyboard(rows: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        buttons.append((_claim_title(row), f"disp_pick:{row['claim_id']}:{page}"))
    if page > 0:
        buttons.append(("⬅️ Назад", f"disp_avail:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("➡️ Вперёд", f"disp_avail:{page + 1}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _dispute_list_keyboard(rows: list[dict], prefix: str) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        period = str(row["period"])[:10]
        volume = float(row["volume_goods"])
        buttons.append((_shorten(f"{period} | {volume:g} | #{row['id']}", 64), f"{prefix}:{row['id']}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _dispute_confirm_step1_keyboard(claim_id: int, page: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("✅ Да, оспорить", f"disp_wait:{claim_id}:{page}"),
            ("❌ Нет", f"disp_avail:{page}"),
        ]
    )


def _dispute_confirm_step2_keyboard(claim_id: int, page: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("✅ Подтверждаю спор", f"disp_confirm:{claim_id}:{page}"),
            ("❌ Отмена", f"disp_avail:{page}"),
        ]
    )


async def _enable_dispute_confirm(
    target_message: Message,
    claim_id: int,
    page: int,
    delay_sec: int,
) -> None:
    await asyncio.sleep(max(1, delay_sec))
    try:
        await target_message.edit_text(
            "Таймер истек. Подтвердите открытие спора.",
            reply_markup=_dispute_confirm_step2_keyboard(claim_id, page),
        )
    except Exception:
        logger.exception("Failed to update dispute confirm timer for claim %s", claim_id)


async def _current_active_user(tg_user_id: int) -> dict | None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if not user or str(user["status"]) != "active":
        return None
    return dict(user)


def _fmt_medcoin(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _finance_main_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("💸 Вывод МЕДкоинов", "fin_withdraw"),
            ("📆 Моя статистика по месяцам", "fin_months:0"),
            ("⬅️ Назад", "sale_back_menu"),
        ]
    )


def _finance_withdraw_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("💳 Вывести на карту", "fin_withdraw_card"),
            ("📆 Моя статистика по месяцам", "fin_months:0"),
            ("⬅️ Назад", "fin_menu"),
        ]
    )


def _withdraw_methods_keyboard(has_current: bool) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    if has_current:
        buttons.append(("✅ Вывести по текущим реквизитам", "fin_req_current"))
    buttons.append(("✍️ Ввести новые реквизиты", "fin_req_new"))
    buttons.append(("⬅️ Назад", "fin_withdraw"))
    return build_inline_keyboard(buttons)


def _withdraw_confirm_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("✅ Подтвердить вывод", "fin_withdraw_confirm"),
            ("❌ Отмена", "fin_menu"),
        ]
    )


def _month_label(month: str) -> str:
    year, mon = month.split("-")
    return f"{mon}.{year}"


def _months_keyboard(months: list[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(months) / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    current = months[start:end]
    buttons: list[tuple[str, str]] = []
    for month in current:
        buttons.append((_month_label(month), f"fin_month_open:{month}:{page}"))
    if page > 0:
        buttons.append(("⬅️ Назад", f"fin_months:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("➡️ Вперёд", f"fin_months:{page + 1}"))
    buttons.append(("⬅️ В меню", "fin_menu"))
    return build_inline_keyboard(buttons)


async def _ensure_finance_seed(user: dict) -> None:
    config = get_config()
    await sqlite.ensure_base_medcoin_earnings_for_claims(
        config.db_path,
        tg_user_id=int(user["tg_user_id"]),
        company_group_id=int(user["company_group_id"]),
        org_id=int(user["org_id"]),
    )


async def _render_finance_menu(message: Message, user: dict, edit: bool = False) -> None:
    config = get_config()
    await _ensure_finance_seed(user)
    totals = await sqlite.get_medcoin_totals(config.db_path, int(user["tg_user_id"]))
    frozen_disputes = await sqlite.get_dispute_frozen_amount(
        config.db_path, int(user["tg_user_id"])
    )
    text = (
        "Финансы:\n"
        f"Доступно: {_fmt_medcoin(totals['available'])} 🍯\n"
        f"Заморожено в спорах: {_fmt_medcoin(frozen_disputes)} 🍯\n"
        f"Заработано всего: {_fmt_medcoin(totals['earned_total'])} 🍯\n"
        f"Выведено всего: {_fmt_medcoin(totals['withdrawn_total'])} 🍯"
    )
    if edit:
        await message.edit_text(text, reply_markup=_finance_main_keyboard())
    else:
        await message.answer(text, reply_markup=_finance_main_keyboard())


async def _render_months_menu(message: Message, user: dict, page: int, edit: bool = True) -> None:
    config = get_config()
    await _ensure_finance_seed(user)
    months = await sqlite.list_finance_months(config.db_path, int(user["tg_user_id"]))
    if not months:
        text = "Нет месяцев с начислениями или выводами."
        kb = build_inline_keyboard([("⬅️ В меню", "fin_menu")])
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return
    page_size = max(1, config.inline_page_size)
    kb = _months_keyboard(months, page, page_size)
    text = "Выберите месяц:"
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


async def _render_month_details(
    message: Message, user: dict, month: str, back_page: int, edit: bool = True
) -> None:
    config = get_config()
    await _ensure_finance_seed(user)
    ledger_totals = await sqlite.get_month_ledger_totals(config.db_path, int(user["tg_user_id"]), month)
    month_claims = await sqlite.get_month_claim_metrics(config.db_path, int(user["tg_user_id"]), month)
    new_buyers = await sqlite.count_new_buyer_inns_for_user_month(
        config.db_path,
        tg_user_id=int(user["tg_user_id"]),
        company_group_id=int(user["company_group_id"]),
        month=month,
    )
    rank = await sqlite.get_company_rank_for_user_org_month(
        config.db_path,
        tg_user_id=int(user["tg_user_id"]),
        org_id=int(user["org_id"]),
        month=month,
    )
    bonus_rows = await sqlite.list_month_bonus_breakdown(
        config.db_path, int(user["tg_user_id"]), month
    )
    bonus_lines = []
    for row in bonus_rows:
        bonus_lines.append(f"- {row['stage_code']}: {_fmt_medcoin(float(row['amount']))} 🍯")
    bonus_text = "\n".join(bonus_lines) if bonus_lines else "- Нет ненулевых начислений"
    today = moscow_today()
    current_month = f"{today.year:04d}-{today.month:02d}"
    frozen_dispute_month = 0.0
    if month == current_month:
        frozen_dispute_month = await sqlite.get_dispute_frozen_amount(
            config.db_path, int(user["tg_user_id"])
        )
    text = (
        f"Статистика за {month}:\n"
        f"Заработано: {_fmt_medcoin(ledger_totals['earned'])} 🍯\n"
        f"Оспорено/заморожено: {_fmt_medcoin(frozen_dispute_month)} 🍯\n"
        f"Выведено: {_fmt_medcoin(ledger_totals['withdrawn'])} 🍯\n"
        f"Литры за месяц: {_fmt_medcoin(float(month_claims['liters']))} л\n"
        f"Место в рейтинге компании: {rank if rank is not None else '-'}\n"
        f"Количество зафиксированных продаж: {int(month_claims['claims_count'])}\n"
        f"Новых ИНН покупателей: {new_buyers}\n\n"
        "Детализация по этапам бонусов:\n"
        f"{bonus_text}"
    )
    kb = build_inline_keyboard(
        [
            ("⬅️ Назад к месяцам", f"fin_months:{back_page}"),
            ("⬅️ В меню", "fin_menu"),
        ]
    )
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


async def _notify_manager_withdraw_request(
    callback: CallbackQuery, user: dict, amount: float
) -> None:
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
    if not org:
        return
    manager_tg_user_id = int(org["created_by_manager_id"])
    role_label = "ROP" if str(user["role"]) == "rop" else "SELLER"
    try:
        await callback.bot.send_message(
            manager_tg_user_id,
            f"{role_label} компании {org['inn']} {org['name']} запросил вывод {_fmt_medcoin(amount)} 🍯",
        )
    except Exception:
        logger.exception(
            "Failed to send withdrawal push manager=%s user=%s",
            manager_tg_user_id,
            int(user["tg_user_id"]),
        )


def _claim_details_text(row: dict) -> str:
    claimed_name = (row.get("claimed_by_full_name") or "").strip() or f"ID {row['claimed_by_tg_user_id']}"
    return (
        "Карточка продажи:\n"
        f"Период: {row['period']}\n"
        f"Покупатель: {row['buyer_name']} ({row['buyer_inn']})\n"
        f"Объем: {float(row['volume_goods']):g}\n"
        f"Зафиксировал: {claimed_name} ({row['claimed_by_tg_user_id']})\n"
        f"Дата фиксации: {row['claimed_at']}"
    )


async def _resolve_dispute_moderator(
    initiator_user: dict,
    claim_row: dict,
) -> int | None:
    # РОП может модерировать свой спор сам (включая спор с собой).
    if str(initiator_user["role"]) == "rop":
        return int(initiator_user["tg_user_id"])
    config = get_config()
    rops = await sqlite.list_active_rops_by_group(
        config.db_path, int(claim_row["company_group_id_at_claim"])
    )
    if not rops:
        return None
    return int(rops[0]["tg_user_id"])


async def _render_available_disputes(message: Message, user: dict, page: int, edit: bool = False) -> None:
    config = get_config()
    total = await sqlite.count_claimed_sales_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
    )
    if total <= 0:
        text = "Нет доступных продаж для спора."
        if edit:
            await message.edit_text(text, reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]))
        else:
            await message.answer(text, reply_markup=seller_main_menu())
        return
    total_pages = max(1, math.ceil(total / DISPUTE_LIST_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_claimed_sales_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
        limit=DISPUTE_LIST_PAGE_SIZE,
        offset=page * DISPUTE_LIST_PAGE_SIZE,
    )
    rows_dict = [dict(r) for r in rows]
    text = "Доступные для спора продажи:"
    kb = _available_disputes_keyboard(rows_dict, page, total_pages)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


def _dispute_details_text(row: dict) -> str:
    return (
        f"Спор #{row['id']}\n"
        f"Период: {row['period']}\n"
        f"Покупатель: {row['buyer_name']} ({row['buyer_inn']})\n"
        f"Объем: {float(row['volume_goods']):g}\n"
        f"Инициатор: {row['initiator_tg_user_id']}\n"
        f"Зафиксировал: {row['claimed_by_tg_user_id']}\n"
        f"Статус: {row['status']}"
    )


@router.message(F.text == SELLER_MENU_DISPUTE)
async def seller_dispute_menu(message: Message) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    kb = build_inline_keyboard(
        [
            ("Доступные для спора", "disp_avail:0"),
            ("Мои спорные", "disp_my"),
            ("Споры со мной", "disp_against"),
            ("⬅️ В меню", "sale_back_menu"),
        ]
    )
    await message.answer("Оспаривание продаж:", reply_markup=kb)


@router.message(F.text == SELLER_MENU_DISPUTE_MODERATE)
async def seller_dispute_moderate_menu(message: Message) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.", reply_markup=seller_main_menu())
        return
    config = get_config()
    rows = await sqlite.list_open_disputes_for_moderator(
        config.db_path,
        moderator_tg_user_id=int(user["tg_user_id"]),
        company_group_id=int(user["company_group_id"]),
    )
    rows_dict = [dict(r) for r in rows]
    if not rows_dict:
        await message.answer("Открытых споров нет.", reply_markup=seller_main_menu())
        return
    await message.answer(
        "Спорные продажи:",
        reply_markup=_dispute_list_keyboard(rows_dict, "disp_mod_open"),
    )


@router.callback_query(F.data.startswith("disp_avail:"))
async def seller_dispute_available(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    _, page_s = callback.data.split(":")
    page = int(page_s)
    await _render_available_disputes(callback.message, user, page, edit=True)


@router.callback_query(F.data.startswith("disp_pick:"))
async def seller_dispute_pick(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    _, claim_id_s, page_s = callback.data.split(":")
    claim_id = int(claim_id_s)
    page = int(page_s)
    config = get_config()
    claim = await sqlite.get_claim_by_id(config.db_path, claim_id)
    if not claim:
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    claim_dict = dict(claim)
    if int(claim_dict["company_group_id_at_claim"]) != int(user["company_group_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    if str(user["role"]) == "seller" and int(claim_dict["claimed_by_tg_user_id"]) == int(user["tg_user_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    if str(claim_dict["dispute_status"]) == "open":
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    await callback.message.edit_text(
        _claim_details_text(claim_dict) + "\n\nОспорить эту продажу?",
        reply_markup=_dispute_confirm_step1_keyboard(claim_id, page),
    )


@router.callback_query(F.data.startswith("disp_wait:"))
async def seller_dispute_wait_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, claim_id_s, page_s = parts
    claim_id = int(claim_id_s)
    page = int(page_s)
    delay_sec = get_config().dispute_confirm_delay_sec
    await callback.message.edit_text(
        f"Подтверждение будет доступно через {delay_sec} сек...",
        reply_markup=build_inline_keyboard([("❌ Отмена", f"disp_avail:{page}")]),
    )
    asyncio.create_task(_enable_dispute_confirm(callback.message, claim_id, page, delay_sec))


@router.callback_query(F.data.startswith("disp_confirm:"))
async def seller_dispute_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    if is_rate_limited(f"disp_confirm:{callback.from_user.id}", limit=6, window_sec=60):
        await callback.message.edit_text(
            "Слишком много попыток оспаривания. Подождите немного.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    _, claim_id_s, page_s = callback.data.split(":")
    claim_id = int(claim_id_s)
    page = int(page_s)
    config = get_config()
    claim = await sqlite.get_claim_by_id(config.db_path, claim_id)
    if not claim:
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    claim_dict = dict(claim)
    if int(claim_dict["company_group_id_at_claim"]) != int(user["company_group_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    if str(user["role"]) == "seller" and int(claim_dict["claimed_by_tg_user_id"]) == int(user["tg_user_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    if str(claim_dict["dispute_status"]) == "open":
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    moderator_id = await _resolve_dispute_moderator(user, claim_dict)
    if moderator_id is None:
        await callback.message.edit_text(
            "Нет активного РОП для модерации спора.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"disp_avail:{page}")]),
        )
        return
    try:
        dispute_id = await sqlite.create_sale_dispute(
            config.db_path,
            claim_id=claim_id,
            initiator_tg_user_id=int(user["tg_user_id"]),
            moderator_tg_user_id=moderator_id,
        )
    except Exception:
        logger.exception("Failed to create dispute for claim %s", claim_id)
        await _render_available_disputes(callback.message, user, page, edit=True)
        return

    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=int(user["tg_user_id"]),
        actor_role=str(user["role"]),
        action="DISPUTE_OPEN",
        payload={"dispute_id": dispute_id, "claim_id": claim_id},
    )

    if config.dispute_push_enabled:
        try:
            await callback.bot.send_message(
                moderator_id,
                "Открыт новый спор по продаже.\n"
                f"Покупатель: {claim_dict['buyer_name']} ({claim_dict['buyer_inn']})\n"
                f"Объем: {float(claim_dict['volume_goods']):g}\n"
                f"Период: {claim_dict['period']}\n"
                f"Спор #{dispute_id}",
            )
        except Exception:
            logger.exception("Failed to notify moderator %s for dispute %s", moderator_id, dispute_id)

    await callback.message.edit_text(
        f"Спор открыт (#{dispute_id}).",
        reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
    )


@router.callback_query(F.data == "disp_my")
async def seller_dispute_my(callback: CallbackQuery) -> None:
    await callback.answer()
    config = get_config()
    rows = await sqlite.list_open_disputes_by_initiator(config.db_path, callback.from_user.id)
    rows_dict = [dict(r) for r in rows]
    if not rows_dict:
        await callback.message.edit_text(
            "У вас нет открытых споров.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await callback.message.edit_text(
        "Мои спорные:",
        reply_markup=_dispute_list_keyboard(rows_dict, "disp_my_open"),
    )


@router.callback_query(F.data.startswith("disp_my_open:"))
async def seller_dispute_my_open(callback: CallbackQuery) -> None:
    await callback.answer()
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    if not dispute or int(dispute["initiator_tg_user_id"]) != callback.from_user.id:
        await callback.message.edit_text(
            "Спор не найден.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await callback.message.edit_text(
        _dispute_details_text(dict(dispute)),
        reply_markup=build_inline_keyboard(
            [
                ("❌ Отменить спор", f"disp_cancel:{dispute_id}"),
                ("⬅️ Назад", "disp_my"),
            ]
        ),
    )


@router.callback_query(F.data.startswith("disp_cancel:"))
async def seller_dispute_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    claim_id = int(dispute["claim_id"]) if dispute else None
    ok = await sqlite.cancel_dispute(config.db_path, dispute_id, callback.from_user.id)
    if not ok:
        await callback.message.edit_text(
            "Не удалось отменить спор.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", "disp_my")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=callback.from_user.id,
        actor_role="seller",
        action="DISPUTE_CANCEL",
        payload={"dispute_id": dispute_id},
    )
    if claim_id is not None:
        sync_result = await sync_claim_goals(config, claim_id)
        if sync_result.get("supertask_completed_id") and config.supertask_push_done_enabled:
            try:
                await callback.bot.send_message(
                    callback.from_user.id,
                    f"Сверхзадача #{sync_result['supertask_completed_id']} выполнена ✅",
                )
            except Exception:
                logger.exception("Failed to send supertask done push to %s", callback.from_user.id)
    await callback.message.edit_text(
        "Спор отменен.",
        reply_markup=build_inline_keyboard([("⬅️ Назад", "disp_my")]),
    )


@router.callback_query(F.data == "disp_against")
async def seller_dispute_against(callback: CallbackQuery) -> None:
    await callback.answer()
    config = get_config()
    rows = await sqlite.list_open_disputes_against_user(config.db_path, callback.from_user.id)
    rows_dict = [dict(r) for r in rows]
    if not rows_dict:
        await callback.message.edit_text(
            "Открытых споров против вас нет.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await callback.message.edit_text(
        "Споры со мной:",
        reply_markup=_dispute_list_keyboard(rows_dict, "disp_against_open"),
    )


@router.callback_query(F.data.startswith("disp_against_open:"))
async def seller_dispute_against_open(callback: CallbackQuery) -> None:
    await callback.answer()
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    if not dispute or int(dispute["claimed_by_tg_user_id"]) != callback.from_user.id:
        await callback.message.edit_text(
            "Спор не найден.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await callback.message.edit_text(
        _dispute_details_text(dict(dispute)),
        reply_markup=build_inline_keyboard([("⬅️ Назад", "disp_against")]),
    )


@router.callback_query(F.data.startswith("disp_mod_open:"))
async def seller_dispute_mod_open(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    if (
        not dispute
        or str(dispute["status"]) != "open"
        or int(dispute["moderator_tg_user_id"]) != int(user["tg_user_id"])
    ):
        await callback.message.edit_text(
            "Спор недоступен.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await callback.message.edit_text(
        _dispute_details_text(dict(dispute)),
        reply_markup=build_inline_keyboard(
            [
                ("✅ Подтвердить спор", f"disp_mod_appr:{dispute_id}"),
                ("❌ Отклонить спор", f"disp_mod_rej:{dispute_id}"),
                ("⬅️ Назад", "sale_back_menu"),
            ]
        ),
    )


@router.callback_query(F.data.startswith("disp_mod_appr:"))
async def seller_dispute_mod_approve(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    claim_id = int(dispute["claim_id"]) if dispute else None
    ok = await sqlite.resolve_dispute(
        config.db_path,
        dispute_id=dispute_id,
        moderator_tg_user_id=int(user["tg_user_id"]),
        approve=True,
    )
    if not ok:
        await callback.message.edit_text(
            "Не удалось подтвердить спор.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=int(user["tg_user_id"]),
        actor_role="rop",
        action="DISPUTE_APPROVE",
        payload={"dispute_id": dispute_id},
    )
    if claim_id is not None:
        sync_result = await sync_claim_goals(config, claim_id)
        if sync_result.get("supertask_completed_id") and config.supertask_push_done_enabled:
            try:
                await callback.bot.send_message(
                    callback.from_user.id,
                    f"Сверхзадача #{sync_result['supertask_completed_id']} выполнена ✅",
                )
            except Exception:
                logger.exception("Failed to send supertask done push to %s", callback.from_user.id)
    await callback.message.edit_text(
        "Спор подтвержден. Продажа передана оспаривающему.",
        reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
    )


@router.callback_query(F.data.startswith("disp_mod_rej:"))
async def seller_dispute_mod_reject(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, dispute_id_s = callback.data.split(":")
    dispute_id = int(dispute_id_s)
    config = get_config()
    dispute = await sqlite.get_dispute_by_id(config.db_path, dispute_id)
    claim_id = int(dispute["claim_id"]) if dispute else None
    ok = await sqlite.resolve_dispute(
        config.db_path,
        dispute_id=dispute_id,
        moderator_tg_user_id=int(user["tg_user_id"]),
        approve=False,
    )
    if not ok:
        await callback.message.edit_text(
            "Не удалось отклонить спор.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=int(user["tg_user_id"]),
        actor_role="rop",
        action="DISPUTE_REJECT",
        payload={"dispute_id": dispute_id},
    )
    if claim_id is not None:
        sync_result = await sync_claim_goals(config, claim_id)
        if sync_result.get("supertask_completed_id") and config.supertask_push_done_enabled:
            try:
                await callback.bot.send_message(
                    callback.from_user.id,
                    f"Сверхзадача #{sync_result['supertask_completed_id']} выполнена ✅",
                )
            except Exception:
                logger.exception("Failed to send supertask done push to %s", callback.from_user.id)
    await callback.message.edit_text(
        "Спор отклонен.",
        reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
    )


def _staff_action_menu(org_id: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            (SELLER_FIRE_ACTIVE, f"staff_mode:{org_id}:active"),
            (SELLER_FIRE_FIRED, f"staff_mode:{org_id}:fired"),
            ("⬅️ В меню", "sale_back_menu"),
        ]
    )


def _staff_list_menu(org_id: int, rows: list[dict], action: str) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        name = (row["full_name"] or "").strip() or f"ID {row['tg_user_id']}"
        buttons.append((f"{name} | {row['tg_user_id']}", f"staff_{action}:{org_id}:{row['tg_user_id']}"))
    buttons.append(("⬅️ Назад", f"staff_open:{org_id}"))
    return build_inline_keyboard(buttons)


def _my_staff_list_menu(rows: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        name = (row["full_name"] or "").strip() or f"ID {row['tg_user_id']}"
        label = f"{name} | {float(row['liters']):g} л | #{int(row['company_rank'])}"
        if len(label) > 64:
            label = label[:61] + "..."
        buttons.append((label, f"my_staff_open:{int(row['tg_user_id'])}:{page}"))
    if page > 0:
        buttons.append(("⬅️ Назад", f"my_staff_page:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("➡️ Вперёд", f"my_staff_page:{page + 1}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _my_staff_profile_menu(staff_tg_user_id: int, page: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("📤 Выгрузить в Excel", f"my_staff_export:{staff_tg_user_id}:{page}"),
            ("⬅️ Назад", f"my_staff_page:{page}"),
        ]
    )


async def _render_my_staff_page(message: Message, rop_user: dict, page: int, edit: bool = True) -> None:
    config = get_config()
    today = moscow_today()
    month = f"{today.year:04d}-{today.month:02d}"
    page_size = max(1, config.inline_page_size)
    total = await sqlite.count_active_sellers_by_org(config.db_path, int(rop_user["org_id"]))
    if total <= 0:
        text = "В вашей компании нет активных продавцов."
        kb = build_inline_keyboard([("⬅️ В меню", "sale_back_menu")])
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return
    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_active_sellers_with_metrics_current_month(
        config.db_path,
        org_id=int(rop_user["org_id"]),
        month=month,
        limit=page_size,
        offset=page * page_size,
    )
    rows_dict = [dict(r) for r in rows]
    text = "Мои сотрудники (активные продавцы):\nФормат: ФИО | литры за месяц | место"
    if edit:
        await message.edit_text(text, reply_markup=_my_staff_list_menu(rows_dict, page, total_pages))
    else:
        await message.answer(text, reply_markup=_my_staff_list_menu(rows_dict, page, total_pages))


@router.message(F.text == SELLER_MENU_FIRE_STAFF)
async def seller_fire_staff_open(message: Message) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user or str(user["status"]) != "active":
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.", reply_markup=seller_main_menu())
        return
    org_id = int(user["org_id"])
    await message.answer("Управление сотрудниками:", reply_markup=_staff_action_menu(org_id))


@router.callback_query(F.data.startswith("staff_open:"))
async def seller_fire_staff_open_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    _, org_id_s = callback.data.split(":")
    await callback.message.edit_text("Управление сотрудниками:", reply_markup=_staff_action_menu(int(org_id_s)))


@router.callback_query(F.data.startswith("staff_mode:"))
async def seller_fire_staff_mode(callback: CallbackQuery) -> None:
    await callback.answer()
    _, org_id_s, mode = callback.data.split(":")
    org_id = int(org_id_s)
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, callback.from_user.id)
    if not user or str(user["status"]) != "active" or str(user["role"]) != "rop" or int(user["org_id"]) != org_id:
        return
    if mode == "active":
        rows = [dict(r) for r in await sqlite.list_sellers_by_org(config.db_path, org_id, 100, 0)]
        if not rows:
            await callback.message.edit_text(
                "Нет активных сотрудников для увольнения.",
                reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
            )
            return
        await callback.message.edit_text(
            "Выберите сотрудника для увольнения:",
            reply_markup=_staff_list_menu(org_id, rows, "fire"),
        )
        return
    rows = [dict(r) for r in await sqlite.list_fired_sellers_by_org(config.db_path, org_id, 100, 0)]
    if not rows:
        await callback.message.edit_text(
            "Нет уволенных сотрудников для восстановления.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
        )
        return
    await callback.message.edit_text(
        "Выберите сотрудника для восстановления:",
        reply_markup=_staff_list_menu(org_id, rows, "restore"),
    )


@router.callback_query(F.data.startswith("staff_fire:"))
async def seller_fire_staff_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    _, org_id_s, tg_user_id_s = callback.data.split(":")
    org_id = int(org_id_s)
    tg_user_id = int(tg_user_id_s)
    config = get_config()
    rop = await sqlite.get_user_by_tg_id(config.db_path, callback.from_user.id)
    if not rop or str(rop["status"]) != "active" or str(rop["role"]) != "rop" or int(rop["org_id"]) != org_id:
        return
    changed = await sqlite.fire_user(
        config.db_path,
        tg_user_id=tg_user_id,
        expected_role="seller",
        fired_by_tg_user_id=callback.from_user.id,
    )
    if not changed:
        await callback.message.edit_text(
            "Не удалось уволить сотрудника (возможно, статус уже изменился).",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=callback.from_user.id,
        actor_role="rop",
        action="FIRE_SELLER",
        payload={"org_id": org_id, "tg_user_id": tg_user_id},
    )
    await callback.message.edit_text(
        "Сотрудник уволен (soft).",
        reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
    )


@router.callback_query(F.data.startswith("staff_restore:"))
async def seller_restore_staff_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    _, org_id_s, tg_user_id_s = callback.data.split(":")
    org_id = int(org_id_s)
    tg_user_id = int(tg_user_id_s)
    config = get_config()
    rop = await sqlite.get_user_by_tg_id(config.db_path, callback.from_user.id)
    if not rop or str(rop["status"]) != "active" or str(rop["role"]) != "rop" or int(rop["org_id"]) != org_id:
        return
    if await sqlite.has_active_registration_in_other_org(config.db_path, tg_user_id, org_id):
        await callback.message.edit_text(
            "Восстановление невозможно: у сотрудника активная регистрация в другой компании.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
        )
        return
    changed = await sqlite.restore_user(
        config.db_path,
        tg_user_id=tg_user_id,
        expected_role="seller",
    )
    if not changed:
        await callback.message.edit_text(
            "Не удалось восстановить сотрудника.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=callback.from_user.id,
        actor_role="rop",
        action="RESTORE_SELLER",
        payload={"org_id": org_id, "tg_user_id": tg_user_id},
    )
    await callback.message.edit_text(
        "Сотрудник восстановлен.",
        reply_markup=build_inline_keyboard([("⬅️ Назад", f"staff_open:{org_id}")]),
    )


@router.message(F.text == SELLER_MENU_MY_STAFF)
async def seller_my_staff_menu(message: Message) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user or str(user["status"]) != "active":
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.", reply_markup=seller_main_menu())
        return
    await _render_my_staff_page(message, dict(user), page=0, edit=False)


@router.callback_query(F.data.startswith("my_staff_page:"))
async def seller_my_staff_page(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, page_s = callback.data.split(":")
    await _render_my_staff_page(callback.message, user, int(page_s), edit=True)


@router.callback_query(F.data.startswith("my_staff_open:"))
async def seller_my_staff_open(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, staff_tg_user_id_s, page_s = callback.data.split(":")
    staff_tg_user_id = int(staff_tg_user_id_s)
    page = int(page_s)
    config = get_config()
    staff_user = await sqlite.get_user_by_tg_id(config.db_path, staff_tg_user_id)
    if (
        not staff_user
        or str(staff_user["status"]) != "active"
        or str(staff_user["role"]) != "seller"
        or int(staff_user["org_id"]) != int(user["org_id"])
    ):
        await _render_my_staff_page(callback.message, user, page=page, edit=True)
        return
    await recalc_all_time_ratings(config.db_path)
    all_time = await get_all_time_for_user(config.db_path, staff_tg_user_id) or {
        "total_volume": 0,
        "global_rank": 0,
        "company_rank": 0,
    }
    prev_month = previous_month(moscow_today())
    prev_snapshot = await get_monthly_snapshot_for_user(
        config.db_path, prev_month, staff_tg_user_id
    ) or {"total_volume": 0, "global_rank": 0, "company_rank": 0}
    today = moscow_today()
    month = f"{today.year:04d}-{today.month:02d}"
    month_metrics = await sqlite.get_user_month_metrics(config.db_path, staff_tg_user_id, month)
    month_rank = await sqlite.get_company_rank_for_user_org_month(
        config.db_path, staff_tg_user_id, int(user["org_id"]), month
    )
    registered_at = format_iso_human(staff_user["registered_at"])
    text = (
        "Профиль сотрудника:\n"
        f"ФИО: {staff_user['full_name']}\n"
        f"ID: {staff_tg_user_id}\n"
        f"Дата регистрации: {registered_at}\n"
        f"Литры за текущий месяц: {float(month_metrics['liters']):g}\n"
        f"Зафиксированных продаж за месяц: {int(month_metrics['claims_count'])}\n"
        f"Место в компании за месяц: {month_rank if month_rank is not None else '-'}\n\n"
        "Рейтинг за всё время: "
        f"{all_time['total_volume']} (в прошлом месяце было {prev_snapshot['total_volume']})\n"
        "Место в мировом рейтинге: "
        f"{all_time['global_rank']} (в прошлом месяце было {prev_snapshot['global_rank']})\n"
        "Место в рейтинге компании: "
        f"{all_time['company_rank']} (в прошлом месяце было {prev_snapshot['company_rank']})"
    )
    await callback.message.edit_text(
        text,
        reply_markup=_my_staff_profile_menu(staff_tg_user_id, page),
    )


@router.callback_query(F.data.startswith("my_staff_export:"))
async def seller_my_staff_export(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user or str(user["role"]) != "rop":
        return
    _, staff_tg_user_id_s, page_s = callback.data.split(":")
    staff_tg_user_id = int(staff_tg_user_id_s)
    page = int(page_s)
    config = get_config()
    staff_user = await sqlite.get_user_by_tg_id(config.db_path, staff_tg_user_id)
    if (
        not staff_user
        or str(staff_user["role"]) != "seller"
        or int(staff_user["org_id"]) != int(user["org_id"])
    ):
        await _render_my_staff_page(callback.message, user, page=page, edit=True)
        return
    path: Path | None = None
    try:
        path = await build_staff_sales_excel(config.db_path, staff_tg_user_id)
        await callback.message.answer_document(
            FSInputFile(path, filename=f"staff_sales_{staff_tg_user_id}.xlsx"),
            caption=f"Продажи сотрудника {staff_tg_user_id} за весь период",
        )
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=int(user["tg_user_id"]),
            actor_role="rop",
            action="ROP_EXPORT_STAFF_SALES",
            payload={"staff_tg_user_id": staff_tg_user_id},
        )
    except Exception:
        logger.exception("Failed to export staff sales for %s", staff_tg_user_id)
        await callback.message.answer("Не удалось сформировать выгрузку.")
    finally:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to remove temporary export file: %s", path)


@router.message(F.text == SELLER_MENU_PROFILE)
async def seller_profile(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    if str(user["status"]) != "active":
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

    rows = await current_month_rankings(config.db_path)
    org_id = int(user["org_id"])
    company_rows = [r for r in rows if r.org_id == org_id]
    league = compute_league(company_rows, message.from_user.id, rank_attr="company_rank")
    challenge = await get_current_challenge(config, message.from_user.id)
    challenge_line = ""
    if challenge:
        if challenge.completed:
            challenge_line = "Челлендж выполнен ✅\n"
        else:
            challenge_line = (
                f"Челлендж: {challenge.progress_volume:g}/{challenge.target_volume:g} л\n"
            )
    league_line = f"Лига: {league.name}"
    if league.to_next_volume is not None:
        league_line += f", до повышения {league.to_next_volume:g} л"

    has_req = await sqlite.has_requisites(config.db_path, message.from_user.id)
    requisites_line = "Реквизиты указаны: Да" if has_req else "Реквизиты указаны: Нет"

    await message.answer(
        "Профиль:\n"
        f"ID: {message.from_user.id}\n"
        f"Дата регистрации: {registered_at}\n"
        f"{requisites_line}\n\n"
        + challenge_line
        + league_line
        + "\n\n"
        "Мой рейтинг за всё время: "
        f"{all_time['total_volume']} (в прошлом месяце было {prev_snapshot['total_volume']})\n"
        "Место в рейтинге компании: "
        f"{all_time['company_rank']} (в прошлом месяце было {prev_snapshot['company_rank']})",
        reply_markup=seller_profile_menu(),
    )


@router.message(F.text == SELLER_MENU_REQUISITES)
async def seller_requisites_start(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    if str(user["status"]) != "active":
        await show_seller_start(message)
        return
    await state.set_state(RequisitesStates.wait_text)
    await message.answer(
        "Введите реквизиты для обновления. Текст будет сохранён; отображаться он не будет.",
        reply_markup=seller_back_menu(),
    )


@router.message(RequisitesStates.wait_text, F.text == BACK_TEXT)
async def seller_requisites_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_seller_menu(message)


@router.message(RequisitesStates.wait_text, F.text)
async def seller_requisites_save(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    if not message.text or not message.text.strip():
        await message.answer("Введите текст реквизитов или нажмите ⬅️ Назад.")
        return
    config = get_config()
    await sqlite.add_requisites(config.db_path, message.from_user.id, message.text.strip())
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role="seller",
        action="REQUISITES_UPDATE",
        payload=None,
    )
    await state.clear()
    await message.answer("Реквизиты обновлены.", reply_markup=seller_main_menu())


@router.message(F.text == SELLER_MENU_FINANCE)
async def seller_finance_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await _render_finance_menu(message, user, edit=False)


@router.message(F.text == SELLER_MENU_GOALS)
async def seller_personal_goals_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    config = get_config()
    text = await render_personal_goals_text(config, user)
    await message.answer(text, reply_markup=seller_main_menu())


@router.callback_query(F.data == "fin_menu")
async def seller_finance_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    await state.clear()
    await _render_finance_menu(callback.message, user, edit=True)


@router.callback_query(F.data == "fin_withdraw")
async def seller_finance_withdraw(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    await state.clear()
    config = get_config()
    await _ensure_finance_seed(user)
    totals = await sqlite.get_medcoin_totals(config.db_path, int(user["tg_user_id"]))
    frozen_disputes = await sqlite.get_dispute_frozen_amount(
        config.db_path, int(user["tg_user_id"])
    )
    available_for_withdraw = max(0.0, totals["available"] - frozen_disputes)
    text = (
        "Вывод МЕДкоинов:\n"
        f"Доступно к выводу: {_fmt_medcoin(available_for_withdraw)} 🍯\n"
        f"(Общий доступный баланс: {_fmt_medcoin(totals['available'])} 🍯)"
    )
    await callback.message.edit_text(text, reply_markup=_finance_withdraw_keyboard())


@router.callback_query(F.data == "fin_withdraw_card")
async def seller_finance_withdraw_card(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    await state.clear()
    config = get_config()
    latest = await sqlite.get_latest_requisites(config.db_path, int(user["tg_user_id"]))
    has_current = latest is not None
    last_line = ""
    if latest:
        last_line = f"\nПоследние реквизиты:\n{latest['content']}"
    await callback.message.edit_text(
        "Способы оплаты:\n"
        "Выберите вариант вывода."
        + last_line,
        reply_markup=_withdraw_methods_keyboard(has_current),
    )


@router.callback_query(F.data == "fin_req_current")
async def seller_finance_requisites_current(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    config = get_config()
    latest = await sqlite.get_latest_requisites(config.db_path, int(user["tg_user_id"]))
    if not latest:
        await callback.message.edit_text(
            "Текущие реквизиты не найдены. Введите новые.",
            reply_markup=build_inline_keyboard([("✍️ Ввести новые реквизиты", "fin_req_new")]),
        )
        return
    await state.set_state(WithdrawalStates.wait_amount)
    await state.update_data(withdraw_requisites=str(latest["content"]))
    await callback.message.answer(
        "Введите сумму вывода в медкоинах (например: 100 или 100.5).",
        reply_markup=seller_back_menu(),
    )


@router.callback_query(F.data == "fin_req_new")
async def seller_finance_requisites_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    await state.set_state(WithdrawalStates.wait_new_requisites)
    await callback.message.answer(
        'Введите новые реквизиты в формате:\n"0000 0000 0000 0000 Иванов Иван Иванович"',
        reply_markup=seller_back_menu(),
    )


@router.message(WithdrawalStates.wait_new_requisites, F.text == BACK_TEXT)
async def seller_finance_requisites_new_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await _render_finance_menu(message, user, edit=False)


@router.message(WithdrawalStates.wait_new_requisites, F.text)
async def seller_finance_requisites_new_input(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await state.clear()
        await show_seller_start(message)
        return
    value = " ".join((message.text or "").strip().split())
    if not validate_card_requisites_line(value):
        await message.answer(
            "Неверный формат.\n"
            'Ожидается строка: "0000 0000 0000 0000 Иванов Иван Иванович"',
            reply_markup=seller_back_menu(),
        )
        return
    config = get_config()
    await sqlite.add_requisites(config.db_path, message.from_user.id, value)
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role=str(user["role"]),
        action="REQUISITES_UPDATE_WITHDRAWAL",
        payload=None,
    )
    await state.set_state(WithdrawalStates.wait_amount)
    await state.update_data(withdraw_requisites=value)
    await message.answer(
        "Реквизиты сохранены. Введите сумму вывода в медкоинах (например: 100 или 100.5).",
        reply_markup=seller_back_menu(),
    )


@router.message(WithdrawalStates.wait_amount, F.text == BACK_TEXT)
async def seller_finance_amount_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await _render_finance_menu(message, user, edit=False)


@router.message(WithdrawalStates.wait_amount, F.text)
async def seller_finance_amount_input(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await state.clear()
        await show_seller_start(message)
        return
    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 100 или 100.5", reply_markup=seller_back_menu())
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.", reply_markup=seller_back_menu())
        return
    config = get_config()
    await _ensure_finance_seed(user)
    totals = await sqlite.get_medcoin_totals(config.db_path, int(user["tg_user_id"]))
    frozen_disputes = await sqlite.get_dispute_frozen_amount(
        config.db_path, int(user["tg_user_id"])
    )
    available_for_withdraw = max(0.0, totals["available"] - frozen_disputes)
    if amount > available_for_withdraw:
        await message.answer(
            f"Недостаточно доступных средств. Доступно к выводу: {_fmt_medcoin(available_for_withdraw)} 🍯",
            reply_markup=seller_back_menu(),
        )
        return
    data = await state.get_data()
    requisites = str(data.get("withdraw_requisites", "")).strip()
    if not requisites:
        await state.clear()
        await message.answer("Не удалось определить реквизиты. Начните заново в разделе Финансы.")
        return
    await state.set_state(WithdrawalStates.wait_confirm)
    await state.update_data(withdraw_amount=amount, withdraw_requisites=requisites)
    await message.answer(
        "Подтверждение вывода:\n"
        f"Сумма: {_fmt_medcoin(amount)} 🍯\n"
        f"Реквизиты: {requisites}\n\n"
        "Подтвердить вывод?",
        reply_markup=_withdraw_confirm_keyboard(),
    )


@router.callback_query(F.data == "fin_withdraw_confirm")
async def seller_finance_withdraw_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if is_rate_limited(f"withdraw_confirm:{callback.from_user.id}", limit=5, window_sec=60):
        await callback.message.edit_text(
            "Слишком много попыток вывода. Подождите немного и попробуйте снова.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
        )
        return
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    data = await state.get_data()
    requisites = str(data.get("withdraw_requisites", "")).strip()
    amount_raw = data.get("withdraw_amount")
    if not requisites or amount_raw is None:
        await state.clear()
        await callback.message.edit_text(
            "Не удалось подтвердить вывод: данные сессии потеряны.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
        )
        return
    amount = float(amount_raw)
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
    if not org:
        await state.clear()
        await callback.message.edit_text(
            "Организация не найдена.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
        )
        return
    await _ensure_finance_seed(user)
    totals = await sqlite.get_medcoin_totals(config.db_path, int(user["tg_user_id"]))
    frozen_disputes = await sqlite.get_dispute_frozen_amount(
        config.db_path, int(user["tg_user_id"])
    )
    available_for_withdraw = max(0.0, totals["available"] - frozen_disputes)
    if amount > available_for_withdraw:
        await state.clear()
        await callback.message.edit_text(
            "Недостаточно средств для вывода. Попробуйте снова в разделе Финансы.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
        )
        return
    try:
        withdrawal_id = await sqlite.create_withdrawal_request(
            config.db_path,
            tg_user_id=int(user["tg_user_id"]),
            company_group_id=int(user["company_group_id"]),
            org_id=int(user["org_id"]),
            manager_tg_user_id=int(org["created_by_manager_id"]),
            requisites_text=requisites,
            amount=amount,
        )
    except ValueError:
        await state.clear()
        await callback.message.edit_text(
            "Недостаточно средств для вывода. Попробуйте снова в разделе Финансы.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
        )
        return
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=int(user["tg_user_id"]),
        actor_role=str(user["role"]),
        action="WITHDRAWAL_REQUEST_CREATE",
        payload={"withdrawal_id": withdrawal_id, "amount": amount},
    )
    await _notify_manager_withdraw_request(callback, user, amount)
    await state.clear()
    await callback.message.edit_text(
        "Ваш запрос на вывод зафиксирован и отправлен вашему менеджеру.",
        reply_markup=build_inline_keyboard([("⬅️ В меню", "fin_menu")]),
    )


@router.message(WithdrawalStates.wait_confirm, F.text == BACK_TEXT)
async def seller_finance_confirm_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await _render_finance_menu(message, user, edit=False)


@router.message(WithdrawalStates.wait_confirm)
async def seller_finance_confirm_wait(message: Message) -> None:
    await message.answer("Для подтверждения используйте кнопку в сообщении выше или нажмите ⬅️ Назад.")


@router.callback_query(F.data.startswith("fin_months:"))
async def seller_finance_months(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    _, page_s = callback.data.split(":")
    page = int(page_s)
    await _render_months_menu(callback.message, user, page=page, edit=True)


@router.callback_query(F.data.startswith("fin_month_open:"))
async def seller_finance_month_open(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    _, month, page_s = callback.data.split(":")
    if len(month) != 7 or month[4] != "-":
        return
    await _render_month_details(callback.message, user, month=month, back_page=int(page_s), edit=True)


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
    seller_inns = await _get_seller_org_inns(message, message.from_user.id)
    if not seller_inns:
        return
    await _render_sales_list(message, seller_inns, page=0)


@router.message(F.text == "🌍 Мировой рейтинг месяца")
async def seller_global_rating(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    await message.answer(
        "Мировой рейтинг недоступен для вашей роли.\n"
        "Используйте «🏢 Рейтинг в компании за месяц».",
        reply_markup=seller_main_menu(),
    )


@router.message(F.text == SELLER_MENU_COMPANY_RATING)
async def seller_company_rating(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    if str(user["status"]) != "active":
        await show_seller_start(message)
        return
    org_id = int(user["org_id"])
    all_rows = await current_month_rankings(config.db_path)
    rows = [r for r in all_rows if r.org_id == org_id]
    rows = sorted(rows, key=lambda r: r.company_rank)
    league_map = {
        r.tg_user_id: compute_league(rows, r.tg_user_id, rank_attr="company_rank").name for r in rows
    }
    league = compute_league(rows, message.from_user.id, rank_attr="company_rank")
    league_line = f"Лига: {league.name}"
    if league.to_next_volume is not None:
        league_line += f", до повышения {league.to_next_volume:g} л"
    text = (
        _render_rating_list(
            "Рейтинг компании за этот месяц",
            rows,
            message.from_user.id,
            use_company_rank=True,
            league_map=league_map,
        )
        + "\n"
        + league_line
    )
    await message.answer(text, reply_markup=seller_back_menu())


@router.callback_query(F.data == "sale_back_menu")
async def seller_sales_back_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await show_seller_menu(callback.message, callback.from_user.id)


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
    seller_inns = await _get_seller_org_inns(callback.message, callback.from_user.id)
    if not seller_inns:
        return
    await _render_sales_list(callback.message, seller_inns, page=page, edit=True)


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
    seller_inns = await _get_seller_org_inns(callback.message, callback.from_user.id)
    if not seller_inns:
        return
    row = await sqlite.get_turnover_by_id(config.db_path, turnover_id)
    if not row or str(row["seller_inn"]) not in seller_inns:
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
        return
    if str(row["period"])[:10] < config.bot_launch_date.isoformat():
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
        return
    if await sqlite.is_turnover_claimed(config.db_path, turnover_id):
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
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
    seller_inns = await _get_seller_org_inns(callback.message, callback.from_user.id)
    if not seller_inns:
        return
    row = await sqlite.get_turnover_by_id(config.db_path, turnover_id)
    if not row or str(row["seller_inn"]) not in seller_inns:
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
        return
    if str(row["period"])[:10] < config.bot_launch_date.isoformat():
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
        return
    if await sqlite.is_turnover_claimed(config.db_path, turnover_id):
        await _render_sales_list(callback.message, seller_inns, page=page, edit=True)
        return
    try:
        await sqlite.claim_turnover(config.db_path, turnover_id, callback.from_user.id)
    except sqlite3.IntegrityError:
        await _render_sales_list(
            callback.message,
            seller_inns,
            page=page,
            note="Эта продажа уже зафиксирована другим пользователем.",
            edit=True,
        )
        return
    except Exception:
        logger.exception("Failed to claim turnover")
        await _render_sales_list(
            callback.message,
            seller_inns,
            page=page,
            note="Не удалось зафиксировать продажу.",
            edit=True,
        )
        return

    post_sync_ok = True
    try:
        claim_row = await sqlite.fetch_one(
            config.db_path,
            "SELECT id FROM sales_claims WHERE turnover_id = ?",
            (turnover_id,),
        )
        if claim_row:
            sync_result = await sync_claim_goals(config, int(claim_row["id"]))
            if sync_result.get("supertask_completed_id") and config.supertask_push_done_enabled:
                try:
                    await callback.bot.send_message(
                        callback.from_user.id,
                        f"Сверхзадача #{sync_result['supertask_completed_id']} выполнена ✅",
                    )
                except Exception:
                    logger.exception("Failed to send supertask done push to %s", callback.from_user.id)
        else:
            logger.warning("Claim row not found right after turnover claim: turnover_id=%s", turnover_id)
        await recalc_all_time_ratings(config.db_path)
        challenge, just_completed = await update_challenge_progress(config, callback.from_user.id)
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=callback.from_user.id,
            actor_role="seller",
            action="CLAIM_TURNOVER",
            payload={"turnover_id": turnover_id},
        )
        if just_completed:
            await callback.message.answer("Челлендж выполнен ✅")
    except Exception:
        post_sync_ok = False
        logger.exception("Post-claim sync failed for turnover_id=%s", turnover_id)

    await _render_sales_list(
        callback.message,
        seller_inns,
        page=page,
        note=(
            "Продажа успешно зафиксирована за вами."
            if post_sync_ok
            else "Продажа зафиксирована, но часть пост-обновлений не выполнена."
        ),
        edit=True,
    )


@router.message(F.text == BACK_TEXT)
async def seller_back(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user and str(user["status"]) == "active":
        await show_seller_menu(message, message.from_user.id)
        return
    await show_seller_start(message)


@router.message()
async def seller_fallback(message: Message, _state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user and str(user["status"]) == "active":
        await message.answer("Пожалуйста, выберите пункт меню.", reply_markup=seller_main_menu())
    else:
        if user and str(user["status"]) == "fired":
            org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
            inn = org["inn"] if org else "-"
            name = org["name"] if org else "Неизвестная организация"
            await message.answer(
                f"Вы уволены из компании {inn} {name}.\n"
                "Нажмите «📝 Регистрация в компании» для новой регистрации.",
                reply_markup=seller_start_menu(),
            )
            return
        await message.answer("Пожалуйста, выберите пункт меню.", reply_markup=seller_start_menu())
