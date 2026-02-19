from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import FSInputFile

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_seller_menu, show_seller_start
from app.handlers.filters import ActiveInlineMenuFilter, NonManagerFilter, PrivateChatFilter
from app.keyboards.common import (
    BACK_TEXT,
    build_inline_keyboard,
    manager_help_inline_keyboard,
    support_contact_line,
    support_inline_keyboard,
)
from app.keyboards.seller import (
    SELLER_FIRE_ACTIVE,
    SELLER_FIRE_FIRED,
    SELLER_MENU_SCROLLS,
    SELLER_MENU_HELP,
    SELLER_MENU_MY_STAFF,
    SELLER_MENU_DISPUTES,
    SELLER_MENU_DISPUTE,
    SELLER_MENU_DISPUTE_MODERATE,
    SELLER_MENU_STAFF_COMPANIES,
    SELLER_MENU_FINANCE,
    SELLER_MENU_FIRE_STAFF,
    SELLER_MENU_GOALS,
    SELLER_MENU_PROFILE,
    SELLER_MENU_REQUISITES,
    SELLER_MENU_COMPANY_RATING,
    SELLER_MENU_RULES,
    SELLER_MENU_SALES,
    SELLER_SCROLLS_APP_HELP,
    SELLER_SCROLLS_HELP,
    SELLER_SCROLLS_SALES_HELP,
    SELLER_ROLE_ROP,
    SELLER_ROLE_SELLER,
    SELLER_START_REGISTER,
    SELLER_SUPPORT,
    seller_back_menu,
    seller_main_menu,
    seller_profile_menu,
    seller_disputes_menu,
    seller_staff_companies_menu,
    seller_role_menu,
    seller_scrolls_menu,
    seller_start_menu,
)
from app.utils.security import verify_password
from app.utils.time import format_iso_human, now_utc_iso
from app.utils.validators import validate_inn
from app.utils.validators import validate_card_requisites_line
from app.utils.rate_limit import is_rate_limited
from app.utils.inline_menu import mark_inline_menu_active, send_single_inline_menu
from app.utils.reply_menu import send_single_reply_menu
from app.utils.nav_history import pop_history, push_history
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
router.callback_query.filter(ActiveInlineMenuFilter())


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
NAV_MAIN = "main"
NAV_PROFILE = "profile"
NAV_DISPUTES = "disputes"
NAV_STAFF_COMPANIES = "staff_companies"
NAV_SCROLLS = "scrolls"
_BONUS_STAGE_LABELS = {
    "avg_level_bonus": "Бонус за среднемесячный уровень",
    "base_claim": "Базовая фиксация",
    "new_buyer_bonus": "Бонус за нового покупателя",
    "pool_bonus": "Бонус за бассейн",
    "supertask_bonus": "Бонус за сверхзадачу",
}


async def _send_error(message: Message) -> None:
    await message.answer("Произошла ошибка, попробуйте позже.", reply_markup=seller_back_menu())


async def _render_nav_screen(message: Message, user: dict, nav_token: str) -> None:
    role = str(user["role"])
    if nav_token == NAV_PROFILE:
        await send_single_reply_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=(
                "👤 Раздел профиля\n"
                "────────────\n"
                "• 📋 Реквизиты - изменить реквизиты для выплат.\n"
                "• 💳 Финансы - баланс, вывод и статистика.\n"
                "• 🎯 Личные цели - прогресс по задачам."
            ),
            reply_markup=seller_profile_menu(),
        )
        return
    if nav_token == NAV_DISPUTES:
        await send_single_reply_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text="⚖️ Раздел споров: арена разборов по продажам.",
            reply_markup=seller_disputes_menu(role=role),
        )
        return
    if nav_token == NAV_STAFF_COMPANIES:
        await send_single_reply_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text="🏢 Раздел сотрудников и компаний: строй команды и управление составом.",
            reply_markup=seller_staff_companies_menu(role=role),
        )
        return
    if nav_token == NAV_SCROLLS:
        await send_single_reply_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=(
                "📜 Выберите раздел Скрижалей легиона:\n"
                "• 📜 Наставления легиона - базовые правила работы.\n"
                "• 📈 Помощь в продажах - связь с менеджером Медоварни.\n"
                "• 🧩 Помощь с приложением - обращение в техподдержку."
            ),
            reply_markup=seller_scrolls_menu(),
        )
        return
    await show_seller_menu(message, int(user["tg_user_id"]))


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_user_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        return datetime.fromisoformat(text[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return text[:10]


def _safe_iso_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


async def _ensure_pool_window(company_group_id: int) -> tuple[str, str]:
    cfg = get_config()
    current = await sqlite.get_pool_state_for_group(cfg.db_path, company_group_id)
    if current:
        return str(current["started_at"]), str(current["ends_at"])

    created_at = await sqlite.get_company_group_created_at(cfg.db_path, company_group_id)
    starts_at = str(created_at) if created_at else now_utc_iso()
    start_dt = _safe_iso_date(starts_at)
    if start_dt is None:
        start_dt = datetime.utcnow().date()
        starts_at = start_dt.isoformat()
    ends_at = (start_dt + timedelta(days=max(0, cfg.pool_days))).isoformat()
    await sqlite.upsert_pool_state_for_group(cfg.db_path, company_group_id, starts_at, ends_at)
    return starts_at, ends_at


async def _bonus_stage_guidance_text(user: dict) -> str:
    cfg = get_config()
    tg_user_id = int(user["tg_user_id"])
    company_group_id = int(user["company_group_id"])
    today = moscow_today()
    month_key = f"{today.year:04d}-{today.month:02d}"
    month_metrics = await sqlite.get_month_claim_metrics(cfg.db_path, tg_user_id, month_key)
    month_liters = float(month_metrics["liters"])

    pool_start, pool_end = await _ensure_pool_window(company_group_id)
    pool_start_date = _safe_iso_date(pool_start)
    pool_end_date = _safe_iso_date(pool_end)
    pool_active = bool(
        pool_start_date and pool_end_date and pool_start_date <= today <= pool_end_date
    )
    if pool_active and pool_end_date:
        pool_status = f"активен, осталось {max(0, (pool_end_date - today).days)} дн."
    elif pool_start_date and today < pool_start_date:
        pool_status = "еще не начался"
    else:
        pool_status = "неактивен"

    supertasks = [
        dict(row)
        for row in await sqlite.list_active_supertasks_for_user(
            cfg.db_path, tg_user_id, company_group_id
        )
    ]
    if supertasks:
        max_reward = max(float(task["reward"]) for task in supertasks)
        supertask_line = (
            f"активно {len(supertasks)} шт., награда до {_fmt_medcoin(max_reward)} 🍯 "
            f"(~{_fmt_medcoin(max_reward)} ₽), литры без фиксированного порога"
        )
    else:
        supertask_line = "активных задач нет, литры без фиксированного порога"

    avg_levels = [
        dict(row) for row in await sqlite.list_active_avg_levels_for_user(cfg.db_path, tg_user_id)
    ]
    nearest_level_text = "активных уровней нет"
    if avg_levels:
        nearest_remain: float | None = None
        nearest_desc = ""
        for level in avg_levels:
            fact_liters = await sqlite.get_sum_liters_between(
                cfg.db_path,
                tg_user_id,
                str(level["starts_at"]),
                str(level["ends_at"]),
            )
            target_liters = float(level["target_liters"])
            remain = max(0.0, target_liters - float(fact_liters))
            if nearest_remain is None or remain < nearest_remain:
                nearest_remain = remain
                reward = float(level["reward"])
                nearest_desc = (
                    f"ближайшая цель {target_liters:g} л, осталось {remain:g} л, "
                    f"награда {_fmt_medcoin(reward)} 🍯 (~{_fmt_medcoin(reward)} ₽)"
                )
        if nearest_desc:
            nearest_level_text = nearest_desc

    return (
        "\n\n🎯 Активные бонусные этапы\n"
        f"1) Бассейн — статус: {pool_status}\n"
        f"Период: {_format_user_date(pool_start)} — {_format_user_date(pool_end)}\n"
        f"Оплата: {_fmt_medcoin(cfg.pool_medcoin_per_liter)} 🍯 за 1 л (~{_fmt_medcoin(cfg.pool_medcoin_per_liter)} ₽/л)\n"
        f"Ваш объем за месяц: {month_liters:g} л\n"
        "Как заработать больше: фиксируйте продажи в день отгрузки и не затягивайте со спорами — в расчет идут подтвержденные литры.\n\n"
        "2) Новый покупатель\n"
        f"Оплата: {_fmt_medcoin(cfg.new_buyer_bonus)} 🍯 (~{_fmt_medcoin(cfg.new_buyer_bonus)} ₽) за первый подтвержденный INN в группе\n"
        "Литры: подходит любой объем первой поставки\n"
        "Как заработать больше: ищите новые INN, быстро фиксируйте первую продажу и проверяйте корректность данных до отправки.\n\n"
        "3) Сверхзадачи\n"
        f"Сейчас: {supertask_line}\n"
        "Как заработать больше: если есть активные задачи, берите их в приоритет и закрывайте раньше других участников.\n\n"
        "4) Среднемесячный уровень\n"
        f"Сейчас: {nearest_level_text}\n"
        "Как заработать больше: ставьте недельный план по литрам и закрывайте его равномерно, чтобы не добирать объем в последний день."
    )


async def _bonus_stage_status_block(user: dict) -> str:
    cfg = get_config()
    tg_user_id = int(user["tg_user_id"])
    company_group_id = int(user["company_group_id"])
    today = moscow_today()
    month_key = f"{today.year:04d}-{today.month:02d}"

    month_metrics = await sqlite.get_month_claim_metrics(cfg.db_path, tg_user_id, month_key)
    month_liters = float(month_metrics["liters"])
    new_buyers = await sqlite.count_new_buyer_inns_for_user_month(
        cfg.db_path,
        tg_user_id=tg_user_id,
        company_group_id=company_group_id,
        month=month_key,
    )

    pool_start, pool_end = await _ensure_pool_window(company_group_id)
    pool_start_date = _safe_iso_date(pool_start)
    pool_end_date = _safe_iso_date(pool_end)
    if pool_start_date and pool_end_date and pool_start_date <= today <= pool_end_date:
        pool_status = f"активен, осталось {max(0, (pool_end_date - today).days)} дн."
    elif pool_start_date and today < pool_start_date:
        pool_status = "еще не начался"
    else:
        pool_status = "неактивен"

    supertasks = await sqlite.list_active_supertasks_for_user(
        cfg.db_path, tg_user_id, company_group_id
    )
    avg_levels = await sqlite.list_active_avg_levels_for_user(cfg.db_path, tg_user_id)
    avg_status = "активных уровней нет"
    if avg_levels:
        nearest_remain: float | None = None
        for level in avg_levels:
            fact_liters = await sqlite.get_sum_liters_between(
                cfg.db_path,
                tg_user_id,
                str(level["starts_at"]),
                str(level["ends_at"]),
            )
            remain = max(0.0, float(level["target_liters"]) - float(fact_liters))
            if nearest_remain is None or remain < nearest_remain:
                nearest_remain = remain
        if nearest_remain is not None:
            avg_status = f"до ближайшей цели осталось {nearest_remain:g} л"

    return (
        "🍯 Бонусные этапы:\n"
        f"• 🏊 Бассейн: {pool_status}, объем {month_liters:g} л\n"
        f"• 🆕 Новый покупатель: +{_fmt_medcoin(cfg.new_buyer_bonus)} 🍯, новых INN за месяц: {new_buyers}\n"
        f"• 🚀 Сверхзадачи: активных {len(supertasks)}\n"
        f"• 📐 Среднемесячный уровень: {avg_status}"
    )


def _format_bonus_stage(stage_code: str) -> str:
    if stage_code == "withdrawal_request":
        return "Запрос на вывод"
    return _BONUS_STAGE_LABELS.get(stage_code, stage_code)


def _format_sale_group_button_text(
    period_date: str, total_volume: float, buyer_inn: str, buyer_name: str, rows_count: int
) -> str:
    volume_text = f"{total_volume:g}"
    buyer_name_short = _shorten(buyer_name, 18)
    period_label = _format_user_date(period_date)
    text = (
        f"📅 {period_label} 🏢 {buyer_inn} "
        f"👤 {buyer_name_short} 📦 {rows_count} 💧 {volume_text} л"
    )
    return _shorten(text, 64)


def _sales_list_keyboard(rows: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        buttons.append(
            (
                _format_sale_group_button_text(
                    row["period_date"],
                    float(row["total_volume"]),
                    row["buyer_inn"],
                    row["buyer_name"],
                    int(row["rows_count"]),
                ),
                f"sale_pick:{row['period_date']}:{row['buyer_inn']}:{page}",
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
    lines = [f"🏆 {title}", "────────────"]
    for r in window:
        rank = r.company_rank if use_company_rank else r.global_rank
        name = _format_name(r.full_name, r.tg_user_id)
        if rank == 1:
            rank_badge = "🥇"
        elif rank == 2:
            rank_badge = "🥈"
        elif rank == 3:
            rank_badge = "🥉"
        else:
            rank_badge = "🔹"
        league_name = "-"
        if league_map and r.tg_user_id in league_map:
            league_name = league_map[r.tg_user_id]
        line = (
            f"{rank_badge} #{rank} | {name}\n"
            f"   📊 Объем: {r.total_volume:g} л | 🛡️ Лига: {league_name}"
        )
        if r.tg_user_id == current_id:
            line = f"<b>{line}</b>"
        lines.append(line)
        lines.append("────────────")
    return "\n".join(lines[:-1])


def _sale_confirm_keyboard(period_date: str, buyer_inn: str, page: int) -> InlineKeyboardMarkup:
    buttons = [
        ("✅ Да", f"sale_confirm:{period_date}:{buyer_inn}:{page}"),
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
    actor_tg_user_id: int,
    seller_inns: list[str],
    page: int,
    note: str | None = None,
    edit: bool = False,
) -> None:
    config = get_config()
    actor_user = await sqlite.get_user_by_tg_id(config.db_path, actor_tg_user_id)
    if not actor_user or str(actor_user["status"]) != "active":
        await show_seller_start(message)
        return
    launch_date_iso = config.bot_launch_date.isoformat()
    total = await sqlite.count_unclaimed_turnover_groups_by_inns(
        config.db_path, seller_inns, launch_date_iso=launch_date_iso
    )
    if total == 0:
        text = "Нет доступных продаж для фиксации."
        if note:
            text = f"{note}\n\n{text}"
        await message.answer(text)
        await show_seller_menu(message, actor_tg_user_id)
        return
    total_pages = max(1, math.ceil(total / SALES_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_unclaimed_turnover_groups_by_inns(
        config.db_path,
        seller_inns,
        SALES_PAGE_SIZE,
        page * SALES_PAGE_SIZE,
        launch_date_iso=launch_date_iso,
    )
    rows_dict = [dict(row) for row in rows]
    header = (
        "Выберите группу продаж для фиксации:\n"
        "Формат кнопки: 📅 дата, 🏢 ИНН, 👤 покупатель, 📦 позиции, 💧 литры."
    )
    if note:
        header = f"{note}\n\n{header}"
    if edit:
        await message.edit_text(
            header,
            reply_markup=_sales_list_keyboard(rows_dict, page, total_pages),
        )
        await mark_inline_menu_active(message, actor_tg_user_id)
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=actor_tg_user_id,
            text=header,
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
    await message.answer(
        "Введите никнейм (уникален по всей базе).", reply_markup=seller_back_menu()
    )


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
    if await sqlite.is_nickname_taken(
        config.db_path, nickname, exclude_tg_user_id=message.from_user.id
    ):
        await message.answer(
            "Такой никнейм уже занят в базе. Введите другой.",
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


@router.message(F.text == SELLER_MENU_SCROLLS)
async def seller_scrolls(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=(
            "📜 Выберите раздел Скрижалей легиона:\n"
            "• 📜 Наставления легиона - правила и рекомендации.\n"
            "• 📈 Помощь в продажах - обращение к менеджеру Медоварни.\n"
            "• 🧩 Помощь с приложением - обращение в техподдержку."
        ),
        reply_markup=seller_scrolls_menu(),
    )


@router.message(F.text == SELLER_SCROLLS_HELP)
async def seller_scrolls_help(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    bonus_text = await _bonus_stage_guidance_text(user)
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=(
            "Скрижали в помощь:\n"
            "1) Отмечай продажи каждый день без пропусков — так растет рейтинг и 🍯 медкоины.\n"
            "2) Держи реквизиты актуальными, чтобы выплаты проходили без задержек.\n"
            "3) Работай на личные цели и челленджи: закрытые этапы дают доп. награду.\n"
            "4) Разбирай спорные продажи быстро и по фактам — это сохраняет темп команды.\n"
            "5) Следи за рейтингом в компании и усиливай слабые точки продаж."
            + bonus_text
        ),
        reply_markup=seller_scrolls_menu(),
    )


@router.message(F.text == SELLER_SCROLLS_SALES_HELP)
async def seller_scrolls_sales_help(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    await message.answer(
        "Легионер, если у тебя сложности с продажами — мы поможем:\n"
        "мерч, специальные условия и практики усиления точки.\n\n"
        "Если у тебя есть идея, как увеличить продажи на точке,\n"
        "нажми кнопку ниже и отправь обращение менеджеру Медоварни.",
        reply_markup=manager_help_inline_keyboard(),
    )


def _claim_group_title(row: dict) -> str:
    period = _format_user_date(str(row["period_date"]))
    volume = float(row["total_volume"])
    buyer_inn = str(row["buyer_inn"])
    claims_count = int(row["claims_count"])
    return _shorten(f"📅 {period} 🏢 {buyer_inn} 📦 {claims_count} 💧 {volume:g} л", 64)


def _available_disputes_keyboard(rows: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        buttons.append((_claim_group_title(row), f"disp_pick:{row['period_date']}:{row['buyer_inn']}:{page}"))
    if page > 0:
        buttons.append(("⬅️ Назад", f"disp_avail:{page - 1}"))
    if page < total_pages - 1:
        buttons.append(("➡️ Вперёд", f"disp_avail:{page + 1}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _dispute_list_keyboard(rows: list[dict], prefix: str) -> InlineKeyboardMarkup:
    buttons: list[tuple[str, str]] = []
    for row in rows:
        period = _format_user_date(str(row["period"]))
        volume = float(row["volume_goods"])
        buttons.append((_shorten(f"📅 {period} 💧 {volume:g} л 🆔 #{row['id']}", 64), f"{prefix}:{row['id']}"))
    buttons.append(("⬅️ В меню", "sale_back_menu"))
    return build_inline_keyboard(buttons)


def _dispute_confirm_step1_keyboard(period_date: str, buyer_inn: str, page: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("✅ Да, оспорить", f"disp_wait:{period_date}:{buyer_inn}:{page}"),
            ("❌ Нет", f"disp_avail:{page}"),
        ]
    )


def _dispute_confirm_step2_keyboard(period_date: str, buyer_inn: str, page: int) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("✅ Подтверждаю спор", f"disp_confirm:{period_date}:{buyer_inn}:{page}"),
            ("❌ Отмена", f"disp_avail:{page}"),
        ]
    )


async def _current_active_user(tg_user_id: int) -> dict | None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if not user or str(user["status"]) != "active":
        return None
    return dict(user)


def _seller_main_menu_for(user: dict | None = None, role: str | None = None):
    resolved_role = role
    if resolved_role is None and user is not None:
        resolved_role = str(user["role"])
    return seller_main_menu(role="rop" if resolved_role == "rop" else "seller")


def _fmt_medcoin(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _finance_main_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        [
            ("💸 Вывод 🍯 МЕДкоинов", "fin_withdraw"),
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
    return f"01.{mon}.{year}"


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
        "🍯 Казна легионера:\n"
        f"Доступно: {_fmt_medcoin(totals['available'])} 🍯\n"
        f"Заморожено в спорах: {_fmt_medcoin(frozen_disputes)} 🍯\n"
        f"Заработано всего: {_fmt_medcoin(totals['earned_total'])} 🍯\n"
        f"Выведено всего: {_fmt_medcoin(totals['withdrawn_total'])} 🍯\n\n"
        "Кнопки:\n"
        "• 💸 Вывод 🍯 МЕДкоинов - открыть сценарий вывода.\n"
        "• 📆 Моя статистика по месяцам - посмотреть детализацию начислений."
    )
    if edit:
        await message.edit_text(text, reply_markup=_finance_main_keyboard())
        await mark_inline_menu_active(message, int(user["tg_user_id"]))
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=text,
            reply_markup=_finance_main_keyboard(),
        )


async def _render_months_menu(message: Message, user: dict, page: int, edit: bool = True) -> None:
    config = get_config()
    await _ensure_finance_seed(user)
    months = await sqlite.list_finance_months(config.db_path, int(user["tg_user_id"]))
    if not months:
        text = "Нет месяцев с начислениями или выводами."
        kb = build_inline_keyboard([("⬅️ В меню", "fin_menu")])
        if edit:
            await message.edit_text(text, reply_markup=kb)
            await mark_inline_menu_active(message, int(user["tg_user_id"]))
        else:
            await send_single_inline_menu(
                message,
                actor_tg_user_id=int(user["tg_user_id"]),
                text=text,
                reply_markup=kb,
            )
        return
    page_size = max(1, config.inline_page_size)
    kb = _months_keyboard(months, page, page_size)
    text = (
        "Выберите месяц:\n"
        "• Нажмите дату месяца, чтобы открыть детализацию.\n"
        "• Стрелки переключают страницы списка."
    )
    if edit:
        await message.edit_text(text, reply_markup=kb)
        await mark_inline_menu_active(message, int(user["tg_user_id"]))
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=text,
            reply_markup=kb,
        )


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
        bonus_lines.append(
            f"- {_format_bonus_stage(str(row['stage_code']))}: {_fmt_medcoin(float(row['amount']))} 🍯"
        )
    bonus_text = "\n".join(bonus_lines) if bonus_lines else "- Нет ненулевых начислений"
    today = moscow_today()
    current_month = f"{today.year:04d}-{today.month:02d}"
    frozen_dispute_month = 0.0
    if month == current_month:
        frozen_dispute_month = await sqlite.get_dispute_frozen_amount(
            config.db_path, int(user["tg_user_id"])
        )
    text = (
        f"Статистика за {_month_label(month)}:\n"
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
        await mark_inline_menu_active(message, int(user["tg_user_id"]))
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=text,
            reply_markup=kb,
        )


async def _notify_manager_withdraw_request(
    callback: CallbackQuery, user: dict, amount: float
) -> None:
    config = get_config()
    org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
    if not org:
        logger.warning(
            "Skip withdrawal manager notify: org is missing for user=%s",
            int(user["tg_user_id"]),
        )
        return
    manager_tg_user_id = int(org["created_by_manager_id"] or 0)
    if manager_tg_user_id <= 0:
        logger.warning(
            "Skip withdrawal manager notify: invalid manager_tg_user_id=%s org_id=%s",
            manager_tg_user_id,
            int(user["org_id"]),
        )
        return
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
        f"Период: {_format_user_date(str(row['period']))}\n"
        f"Покупатель: {row['buyer_name']} ({row['buyer_inn']})\n"
        f"Объем: {float(row['volume_goods']):g}\n"
        f"Зафиксировал: {claimed_name} ({row['claimed_by_tg_user_id']})\n"
        f"Дата фиксации: {_format_user_date(str(row['claimed_at']))}"
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
    total = await sqlite.count_claimed_sale_groups_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
    )
    if total <= 0:
        text = "Нет доступных продаж для спора."
        if edit:
            await message.edit_text(text, reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]))
            await mark_inline_menu_active(message, int(user["tg_user_id"]))
        else:
            await message.answer(text)
            await show_seller_menu(message, int(user["tg_user_id"]))
        return
    total_pages = max(1, math.ceil(total / DISPUTE_LIST_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await sqlite.list_claimed_sale_groups_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
        limit=DISPUTE_LIST_PAGE_SIZE,
        offset=page * DISPUTE_LIST_PAGE_SIZE,
    )
    rows_dict = [dict(r) for r in rows]
    text = "Доступные для спора группы продаж:"
    kb = _available_disputes_keyboard(rows_dict, page, total_pages)
    if edit:
        await message.edit_text(text, reply_markup=kb)
        await mark_inline_menu_active(message, int(user["tg_user_id"]))
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=int(user["tg_user_id"]),
            text=text,
            reply_markup=kb,
        )


def _dispute_details_text(row: dict) -> str:
    initiator_label = _person_label(row.get("initiator_full_name"), int(row["initiator_tg_user_id"]))
    claimed_by_label = _person_label(row.get("claimed_by_full_name"), int(row["claimed_by_tg_user_id"]))
    claim_count = int(row.get("claim_count") or 1)
    return (
        f"Спор #{row['id']}\n"
        f"Период: {row['period']}\n"
        f"Покупатель: {row['buyer_name']} ({row['buyer_inn']})\n"
        f"Позиции в группе: {claim_count}\n"
        f"Объем: {float(row['volume_goods']):g}\n"
        f"Инициатор: {initiator_label}\n"
        f"Зафиксировал: {claimed_by_label}\n"
        f"Статус: {row['status']}"
    )


def _person_label(full_name: str | None, tg_user_id: int) -> str:
    name = (full_name or "").strip()
    return f"{name} ({tg_user_id})" if name else f"ID {tg_user_id}"


def _row_full_name(row: dict | sqlite3.Row | None) -> str | None:
    if row is None:
        return None
    try:
        return row["full_name"]
    except Exception:
        return None


def _dispute_resolution_push_text(dispute: dict, moderator_name: str, approve: bool) -> str:
    result_line = "подтвержден" if approve else "отклонен"
    outcome_line = (
        "Продажа передана инициатору спора."
        if approve
        else "Продажа остается за текущим фиксатором."
    )
    initiator_label = _person_label(dispute.get("initiator_full_name"), int(dispute["initiator_tg_user_id"]))
    claimed_by_label = _person_label(dispute.get("claimed_by_full_name"), int(dispute["claimed_by_tg_user_id"]))
    claim_count = int(dispute.get("claim_count") or 1)
    return (
        f"Результат по спору #{dispute['id']}:\n"
        f"Статус: {result_line}\n"
        f"Решение принял: {moderator_name}\n"
        f"Инициатор: {initiator_label}\n"
        f"Зафиксировал: {claimed_by_label}\n"
        f"Период: {_format_user_date(str(dispute['period']))}\n"
        f"Покупатель: {dispute['buyer_name']} ({dispute['buyer_inn']})\n"
        f"Позиции в группе: {claim_count}\n"
        f"Объем: {float(dispute['volume_goods']):g}\n"
        f"{outcome_line}"
    )


async def _notify_dispute_resolution_participants(
    callback: CallbackQuery,
    dispute: dict,
    moderator: dict,
    approve: bool,
) -> None:
    moderator_name = _person_label(str(moderator.get("full_name", "")), int(moderator["tg_user_id"]))
    text = _dispute_resolution_push_text(dispute, moderator_name=moderator_name, approve=approve)
    status_key = "approved" if approve else "rejected"
    recipients = {
        int(dispute["initiator_tg_user_id"]),
        int(dispute["claimed_by_tg_user_id"]),
    }
    for recipient_id in recipients:
        if is_rate_limited(
            f"disp_result_notify:{dispute['id']}:{status_key}:{recipient_id}",
            limit=1,
            window_sec=24 * 60 * 60,
        ):
            continue
        try:
            await callback.bot.send_message(recipient_id, text)
        except Exception:
            logger.exception(
                "Failed to send dispute resolution notification dispute=%s recipient=%s",
                dispute["id"],
                recipient_id,
            )


@router.message(F.text == SELLER_MENU_DISPUTES)
async def seller_disputes_root(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
    await message.answer(
        "⚖️ Раздел споров: здесь открываются и сопровождаются спорные продажи.",
        reply_markup=seller_disputes_menu(role=str(user["role"])),
    )


@router.message(F.text == SELLER_MENU_DISPUTE)
async def seller_dispute_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_DISPUTES)
    kb = build_inline_keyboard(
        [
            ("Доступные для спора", "disp_avail:0"),
            ("Мои спорные", "disp_my"),
            ("Споры со мной", "disp_against"),
            ("⬅️ В меню", "sale_back_menu"),
        ]
    )
    await send_single_inline_menu(
        message,
        actor_tg_user_id=int(user["tg_user_id"]),
        text="⚖️ Арена споров по продажам:",
        reply_markup=kb,
    )


@router.message(F.text == SELLER_MENU_DISPUTE_MODERATE)
async def seller_dispute_moderate_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.")
        await show_seller_menu(message, int(user["tg_user_id"]))
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_DISPUTES)
    config = get_config()
    rows = await sqlite.list_open_disputes_for_moderator(
        config.db_path,
        moderator_tg_user_id=int(user["tg_user_id"]),
        company_group_id=int(user["company_group_id"]),
    )
    rows_dict = [dict(r) for r in rows]
    if not rows_dict:
        await message.answer("Открытых споров нет.")
        await show_seller_menu(message, int(user["tg_user_id"]))
        return
    await send_single_inline_menu(
        message,
        actor_tg_user_id=int(user["tg_user_id"]),
        text="Спорные продажи:",
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
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    _, period_date, buyer_inn, page_s = parts
    page = int(page_s)
    config = get_config()
    claims = await sqlite.list_claimed_sales_in_group_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        period_date=period_date,
        buyer_inn=buyer_inn,
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
    )
    if not claims:
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    claims_dict = [dict(c) for c in claims]
    claimed_by_ids = {int(c["claimed_by_tg_user_id"]) for c in claims_dict}
    if len(claimed_by_ids) != 1:
        await callback.message.edit_text(
            "Группа содержит продажи разных фиксаторов. Откройте спор по другой группе.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"disp_avail:{page}")]),
        )
        return
    if str(user["role"]) == "seller" and int(next(iter(claimed_by_ids))) == int(user["tg_user_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    total_volume = sum(float(c["volume_goods"]) for c in claims_dict)
    group_buyer_name = claims_dict[0]["buyer_name"]
    claimed_by_name = _person_label(
        claims_dict[0].get("claimed_by_full_name"),
        int(claims_dict[0]["claimed_by_tg_user_id"]),
    )
    lines = [
        f"- {c['nomenclature']}: {float(c['volume_goods']):g}"
        for c in claims_dict[:12]
    ]
    if len(claims_dict) > 12:
        lines.append(f"... и еще {len(claims_dict) - 12} поз.")
    details = (
        "Карточка группы продаж:\n"
        f"Период: {_format_user_date(period_date)}\n"
        f"Покупатель: {group_buyer_name} ({buyer_inn})\n"
        f"Позиции: {len(claims_dict)}\n"
        f"Объем группы: {total_volume:g}\n"
        f"Зафиксировал: {claimed_by_name}\n\n"
        "Детализация по номенклатуре:\n"
        + ("\n".join(lines) if lines else "-")
        + "\n\nОспорить всю группу?"
    )
    await callback.message.edit_text(
        details,
        reply_markup=_dispute_confirm_step1_keyboard(period_date, buyer_inn, page),
    )


@router.callback_query(F.data.startswith("disp_wait:"))
async def seller_dispute_wait_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    _, period_date, buyer_inn, page_s = parts
    page = int(page_s)
    await callback.message.edit_text(
        "Подтвердите открытие спора.",
        reply_markup=_dispute_confirm_step2_keyboard(period_date, buyer_inn, page),
    )


@router.callback_query(F.data.startswith("disp_confirm:"))
async def seller_dispute_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    _, period_date, buyer_inn, page_s = parts
    page = int(page_s)
    config = get_config()
    if is_rate_limited(
        f"disp_confirm:{callback.from_user.id}",
        limit=config.dispute_open_limit,
        window_sec=config.dispute_open_window_sec,
    ):
        await callback.message.edit_text(
            "Слишком много попыток оспаривания. Подождите немного.",
            reply_markup=build_inline_keyboard([("⬅️ В меню", "sale_back_menu")]),
        )
        return
    if is_rate_limited(
        f"disp_confirm_action:{callback.from_user.id}:{period_date}:{buyer_inn}",
        limit=1,
        window_sec=config.dispute_open_action_cooldown_sec,
    ):
        await callback.answer(
            "Повторное открытие этого спора временно ограничено.",
            show_alert=True,
        )
        return
    if is_rate_limited(
        f"disp_confirm_global:{callback.from_user.id}",
        limit=1,
        window_sec=config.dispute_open_global_cooldown_sec,
    ):
        await callback.answer(
            f"Новый спор можно открыть через {config.dispute_open_global_cooldown_sec} сек.",
            show_alert=True,
        )
        return
    user = await _current_active_user(callback.from_user.id)
    if not user:
        return
    claims = await sqlite.list_claimed_sales_in_group_for_dispute(
        config.db_path,
        company_group_id=int(user["company_group_id"]),
        period_date=period_date,
        buyer_inn=buyer_inn,
        viewer_tg_user_id=int(user["tg_user_id"]),
        viewer_role=str(user["role"]),
    )
    if not claims:
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    claims_dict = [dict(c) for c in claims]
    claimed_by_ids = {int(c["claimed_by_tg_user_id"]) for c in claims_dict}
    if len(claimed_by_ids) != 1:
        await callback.message.edit_text(
            "Группа содержит продажи разных фиксаторов. Откройте спор по другой группе.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"disp_avail:{page}")]),
        )
        return
    claim_seed = claims_dict[0]
    if str(user["role"]) == "seller" and int(claim_seed["claimed_by_tg_user_id"]) == int(user["tg_user_id"]):
        await _render_available_disputes(callback.message, user, page, edit=True)
        return
    moderator_id = await _resolve_dispute_moderator(user, claim_seed)
    if moderator_id is None:
        await callback.message.edit_text(
            "Нет активного РОП для модерации спора.",
            reply_markup=build_inline_keyboard([("⬅️ Назад", f"disp_avail:{page}")]),
        )
        return
    try:
        dispute_id = await sqlite.create_sale_dispute_group(
            config.db_path,
            company_group_id=int(user["company_group_id"]),
            period_date=period_date,
            buyer_inn=buyer_inn,
            initiator_tg_user_id=int(user["tg_user_id"]),
            moderator_tg_user_id=moderator_id,
        )
    except Exception:
        logger.exception("Failed to create dispute for group %s/%s", period_date, buyer_inn)
        await _render_available_disputes(callback.message, user, page, edit=True)
        return

    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=int(user["tg_user_id"]),
        actor_role=str(user["role"]),
        action="DISPUTE_OPEN",
        payload={"dispute_id": dispute_id, "period_date": period_date, "buyer_inn": buyer_inn},
    )

    if config.dispute_push_enabled:
        try:
            initiator_label = _person_label(_row_full_name(user), int(user["tg_user_id"]))
            total_volume = sum(float(c["volume_goods"]) for c in claims_dict)
            await callback.bot.send_message(
                moderator_id,
                "Открыт новый спор по группе продаж.\n"
                f"Инициатор: {initiator_label}\n"
                f"Покупатель: {claim_seed['buyer_name']} ({claim_seed['buyer_inn']})\n"
                f"Объем группы: {total_volume:g}\n"
                f"Период: {_format_user_date(period_date)}\n"
                f"Позиции: {len(claims_dict)}\n"
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
                ("⬅️ Назад", "disp_mod"),
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
    if dispute:
        await _notify_dispute_resolution_participants(
            callback=callback,
            dispute=dict(dispute),
            moderator=user,
            approve=True,
        )
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
    if dispute:
        await _notify_dispute_resolution_participants(
            callback=callback,
            dispute=dict(dispute),
            moderator=user,
            approve=False,
        )
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
            await mark_inline_menu_active(message, int(rop_user["tg_user_id"]))
        else:
            await send_single_inline_menu(
                message,
                actor_tg_user_id=int(rop_user["tg_user_id"]),
                text=text,
                reply_markup=kb,
            )
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
        await mark_inline_menu_active(message, int(rop_user["tg_user_id"]))
    else:
        await send_single_inline_menu(
            message,
            actor_tg_user_id=int(rop_user["tg_user_id"]),
            text=text,
            reply_markup=_my_staff_list_menu(rows_dict, page, total_pages),
        )


@router.message(F.text == SELLER_MENU_STAFF_COMPANIES)
async def seller_staff_companies_root(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
    if str(user["role"]) != "rop":
        await message.answer("Раздел сотрудников и компаний доступен только роли РОП.")
        await show_seller_menu(message, int(user["tg_user_id"]))
        return
    await send_single_reply_menu(
        message,
        actor_tg_user_id=int(user["tg_user_id"]),
        text="🏢 Раздел сотрудников и компаний: управление сотрудниками вашей компании.",
        reply_markup=seller_staff_companies_menu(role=str(user["role"])),
    )


@router.message(F.text == SELLER_MENU_FIRE_STAFF)
async def seller_fire_staff_open(message: Message, state: FSMContext) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user or str(user["status"]) != "active":
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.")
        await show_seller_menu(message, int(user["tg_user_id"]))
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_STAFF_COMPANIES)
    org_id = int(user["org_id"])
    await send_single_inline_menu(
        message,
        actor_tg_user_id=int(user["tg_user_id"]),
        text="Управление сотрудниками:",
        reply_markup=_staff_action_menu(org_id),
    )


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
async def seller_my_staff_menu(message: Message, state: FSMContext) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user or str(user["status"]) != "active":
        await show_seller_start(message)
        return
    if str(user["role"]) != "rop":
        await message.answer("Этот раздел доступен только роли РОП.")
        await show_seller_menu(message, int(user["tg_user_id"]))
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_STAFF_COMPANIES)
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
    staff_label = _person_label(_row_full_name(staff_user), staff_tg_user_id)
    text = (
        "Профиль сотрудника:\n"
        f"Сотрудник: {staff_label}\n"
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
        staff_label = _person_label(_row_full_name(staff_user), staff_tg_user_id)
        path = await build_staff_sales_excel(config.db_path, staff_tg_user_id)
        await callback.message.answer_document(
            FSInputFile(path, filename=f"staff_sales_{staff_tg_user_id}.xlsx"),
            caption=f"Продажи сотрудника {staff_label} за весь период",
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
async def seller_profile(message: Message, state: FSMContext) -> None:
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
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
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
            challenge_line = "Испытание месяца пройдено ✅\n"
        else:
            challenge_line = (
                f"Испытание месяца: {challenge.progress_volume:g}/{challenge.target_volume:g} л\n"
            )
    league_line = f"Лига компании: {league.name}"
    if league.to_next_volume is not None:
        league_line += f", до повышения {league.to_next_volume:g} л"

    has_req = await sqlite.has_requisites(config.db_path, message.from_user.id)
    requisites_line = "✅ Указаны" if has_req else "❌ Не указаны"
    profile_label = _person_label(_row_full_name(user), message.from_user.id)

    challenge_block = "🎯 Испытание месяца: пока не назначено"
    if challenge:
        if challenge.completed:
            challenge_block = "🎯 Испытание месяца: пройдено ✅"
        else:
            challenge_block = (
                f"🎯 Испытание месяца: {challenge.progress_volume:g}/{challenge.target_volume:g} л"
            )
    bonus_stage_block = await _bonus_stage_status_block(dict(user))

    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=(
            "👤 Ваш профиль\n"
            "────────────\n"
            f"🙋 Пользователь: {profile_label}\n"
            f"🏷️ Никнейм: {_escape_html(str(user['nickname']))}\n"
            f"📅 Дата регистрации: {registered_at}\n"
            f"💳 Реквизиты: {requisites_line}\n\n"
            "🏅 Статус и прогресс\n"
            f"{challenge_block}\n"
            f"🛡️ {league_line}\n"
            f"{bonus_stage_block}\n\n"
            "📈 Рейтинг\n"
            f"💧 Объем за всё время: {all_time['total_volume']} л "
            f"(в прошлом месяце: {prev_snapshot['total_volume']} л)\n"
            "🏢 Место в рейтинге компании: "
            f"{all_time['company_rank']} (в прошлом месяце: {prev_snapshot['company_rank']})\n"
            "🌍 Место в мировом рейтинге: "
            f"{all_time['global_rank']} (в прошлом месяце: {prev_snapshot['global_rank']})"
        ),
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
    await push_history(message.from_user.id, NAV_PROFILE)
    await state.set_state(RequisitesStates.wait_text)
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=(
            "Введите реквизиты в формате:\n"
            '"0000 0000 0000 0000 Иванов Иван Иванович"\n'
            "Проверка формата такая же, как при вводе реквизитов для вывода."
        ),
        reply_markup=seller_back_menu(),
    )


@router.message(RequisitesStates.wait_text, F.text == BACK_TEXT)
async def seller_requisites_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await send_single_reply_menu(
        message,
        actor_tg_user_id=int(user["tg_user_id"]),
        text=(
            "👤 Раздел профиля:\n"
            "• 📋 Реквизиты - изменить реквизиты для выплат.\n"
            "• 💳 Финансы - баланс, вывод и статистика.\n"
            "• 🎯 Личные цели - прогресс по задачам."
        ),
        reply_markup=seller_profile_menu(),
    )


@router.message(RequisitesStates.wait_text, F.text)
async def seller_requisites_save(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    if not message.text or not message.text.strip():
        await message.answer("Введите текст реквизитов или нажмите ⬅️ Назад.")
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
        actor_role="seller",
        action="REQUISITES_UPDATE",
        payload=None,
    )
    await state.clear()
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text="Реквизиты обновлены.",
        reply_markup=seller_profile_menu(),
    )


@router.message(F.text == SELLER_MENU_FINANCE)
async def seller_finance_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_PROFILE)
    await _render_finance_menu(message, user, edit=False)


@router.message(F.text == SELLER_MENU_GOALS)
async def seller_personal_goals_menu(message: Message, state: FSMContext) -> None:
    user = await _current_active_user(message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_PROFILE)
    config = get_config()
    text = await render_personal_goals_text(config, user)
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=text,
        reply_markup=seller_profile_menu(),
    )


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
        "Вывод 🍯 МЕДкоинов:\n"
        f"Доступно к выводу: {_fmt_medcoin(available_for_withdraw)} 🍯\n"
        f"(Общий доступный баланс: {_fmt_medcoin(totals['available'])} 🍯)\n\n"
        "Кнопки:\n"
        "• 💳 Вывести на карту - перейти к реквизитам и сумме.\n"
        "• 📆 Моя статистика по месяцам - детализация начислений."
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
        "Введите сумму вывода в 🍯 медкоинах (например: 100 или 100.5).",
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
        "Реквизиты сохранены. Введите сумму вывода в 🍯 медкоинах (например: 100 или 100.5).",
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


@router.message(F.text.in_({SELLER_SCROLLS_APP_HELP, SELLER_MENU_HELP}))
async def seller_help(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    await message.answer(
        "Помощь с приложением:\n"
        "бот помогает со строем: регистрация, фиксация продаж, споры, казна и личные цели.\n"
        "Если в боевом темпе возникли сложности — напишите в техподдержку.\n\n"
        "Кнопки:\n"
        "• 📝 Оставить обращение - отправка запроса в ТП внутри бота.\n"
        "• 👉 Написать в Telegram - прямой переход в чат поддержки."
        + support_contact_line(config.support_username),
        reply_markup=support_inline_keyboard(config.support_user_id, config.support_username),
    )


@router.message(F.text == SELLER_MENU_SALES)
async def seller_sales_menu(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
    seller_inns = await _get_seller_org_inns(message, message.from_user.id)
    if not seller_inns:
        return
    await _render_sales_list(message, message.from_user.id, seller_inns, page=0)


@router.message(F.text == "🌍 Мировой рейтинг месяца")
async def seller_global_rating(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    user = await _current_active_user(message.from_user.id)
    await message.answer(
        "Мировой рейтинг недоступен для вашей роли.\n"
        "Используйте «🏢 Рейтинг».",
    )
    if user:
        await show_seller_menu(message, int(user["tg_user_id"]))
    else:
        await show_seller_start(message)


@router.message(F.text == SELLER_MENU_COMPANY_RATING)
async def seller_company_rating(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    await state.clear()
    await push_history(message.from_user.id, NAV_MAIN)
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
async def seller_sales_back_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _current_active_user(callback.from_user.id)
    if not user:
        await show_seller_start(callback.message)
        return
    nav_token = await pop_history(callback.from_user.id)
    if not nav_token:
        await show_seller_menu(callback.message, callback.from_user.id)
        return
    await state.clear()
    await _render_nav_screen(callback.message, user, nav_token)


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
    await _render_sales_list(
        callback.message, callback.from_user.id, seller_inns, page=page, edit=True
    )


@router.callback_query(F.data.startswith("sale_pick:"))
async def seller_sales_pick(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    _, period_date, buyer_inn, page_s = parts
    page = int(page_s)
    config = get_config()
    seller_inns = await _get_seller_org_inns(callback.message, callback.from_user.id)
    if not seller_inns:
        return
    rows = await sqlite.list_unclaimed_turnover_rows_by_group(
        config.db_path,
        seller_inns=seller_inns,
        period_date=period_date,
        buyer_inn=buyer_inn,
        launch_date_iso=config.bot_launch_date.isoformat(),
    )
    if not rows:
        await _render_sales_list(
            callback.message, callback.from_user.id, seller_inns, page=page, edit=True
        )
        return
    rows_dict = [dict(r) for r in rows]
    total_volume = sum(float(r["volume_goods"]) for r in rows_dict)
    buyer_name = rows_dict[0]["buyer_name"]
    details_lines = [f"- {r['nomenclature']}: {float(r['volume_goods']):g}" for r in rows_dict[:12]]
    if len(rows_dict) > 12:
        details_lines.append(f"... и еще {len(rows_dict) - 12} поз.")
    details = (
        "Карточка группы продаж:\n"
        f"Период: {_format_user_date(period_date)}\n"
        f"ПокупательИНН: {buyer_inn}\n"
        f"Покупатель: {buyer_name}\n"
        f"Позиции: {len(rows_dict)}\n"
        f"ОбъемТоваров (группа): {total_volume:g}\n\n"
        "Детализация:\n"
        + ("\n".join(details_lines) if details_lines else "-")
        + "\n\nПодтвердить фиксацию всей группы?"
    )
    await callback.message.edit_text(details, reply_markup=_sale_confirm_keyboard(period_date, buyer_inn, page))


@router.callback_query(F.data.startswith("sale_confirm:"))
async def seller_sales_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    _, period_date, buyer_inn, page_s = parts
    page = int(page_s)
    config = get_config()
    # Temporary hotfix: sale confirmation anti-spam timers are disabled.
    # Data integrity is still protected by DB constraints in claim operation.
    seller_inns = await _get_seller_org_inns(callback.message, callback.from_user.id)
    if not seller_inns:
        await callback.answer("Не найдены доступные компании для фиксации.", show_alert=True)
        return
    group_rows = await sqlite.list_unclaimed_turnover_rows_by_group(
        config.db_path,
        seller_inns=seller_inns,
        period_date=period_date,
        buyer_inn=buyer_inn,
        launch_date_iso=config.bot_launch_date.isoformat(),
    )
    if not group_rows:
        await _render_sales_list(
            callback.message, callback.from_user.id, seller_inns, page=page, edit=True
        )
        return
    group_rows_dict = [dict(r) for r in group_rows]
    group_volume = sum(float(r["volume_goods"]) for r in group_rows_dict)
    try:
        claim_ids = await sqlite.claim_turnover_group_by_inns(
            config.db_path,
            seller_inns=seller_inns,
            period_date=period_date,
            buyer_inn=buyer_inn,
            tg_user_id=callback.from_user.id,
            launch_date_iso=config.bot_launch_date.isoformat(),
        )
        if not claim_ids:
            await _render_sales_list(
                callback.message,
                callback.from_user.id,
                seller_inns,
                page=page,
                note="Эта группа уже зафиксирована другим пользователем.",
                edit=True,
            )
            return
    except sqlite3.IntegrityError:
        await _render_sales_list(
            callback.message,
            callback.from_user.id,
            seller_inns,
            page=page,
            note="Эта группа уже зафиксирована другим пользователем.",
            edit=True,
        )
        return
    except Exception:
        logger.exception("Failed to claim turnover group period=%s buyer=%s", period_date, buyer_inn)
        await _render_sales_list(
            callback.message,
            callback.from_user.id,
            seller_inns,
            page=page,
            note="Не удалось зафиксировать группу продаж.",
            edit=True,
        )
        return

    post_sync_ok = True
    try:
        completed_task_ids: set[int] = set()
        for claim_id in claim_ids:
            sync_result = await sync_claim_goals(config, int(claim_id))
            done_id = sync_result.get("supertask_completed_id")
            if done_id:
                completed_task_ids.add(int(done_id))
        if completed_task_ids and config.supertask_push_done_enabled:
            try:
                await callback.bot.send_message(
                    callback.from_user.id,
                    "Сверхзадачи выполнены ✅: " + ", ".join(f"#{x}" for x in sorted(completed_task_ids)),
                )
            except Exception:
                logger.exception("Failed to send supertask done push to %s", callback.from_user.id)
        await recalc_all_time_ratings(config.db_path)
        challenge, just_completed = await update_challenge_progress(config, callback.from_user.id)
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=callback.from_user.id,
            actor_role="seller",
            action="CLAIM_TURNOVER",
            payload={
                "period_date": period_date,
                "buyer_inn": buyer_inn,
                "claims_count": len(claim_ids),
                "group_volume": group_volume,
            },
        )
        if just_completed:
            await callback.message.answer("Испытание месяца пройдено ✅")
    except Exception:
        post_sync_ok = False
        logger.exception("Post-claim sync failed for turnover group period=%s buyer=%s", period_date, buyer_inn)

    await _render_sales_list(
        callback.message,
        callback.from_user.id,
        seller_inns,
        page=page,
        note=(
            f"Группа продаж успешно зафиксирована за вами ({len(claim_ids)} поз., {group_volume:g} л)."
            if post_sync_ok
            else "Группа зафиксирована, но часть пост-обновлений не выполнена."
        ),
        edit=True,
    )
    if post_sync_ok:
        await callback.message.answer(
            "✅ Фиксация продажи выполнена.\n"
            f"📅 Дата: {_format_user_date(period_date)}\n"
            f"🏢 ИНН покупателя: {buyer_inn}\n"
            f"📦 Позиции: {len(claim_ids)}\n"
            f"💧 Объем группы: {group_volume:g} л"
        )


@router.message(F.text == BACK_TEXT)
async def seller_back(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    user = await _current_active_user(message.from_user.id)
    if user:
        nav_token = await pop_history(message.from_user.id)
        await state.clear()
        if not nav_token:
            await show_seller_menu(message, message.from_user.id)
            return
        await _render_nav_screen(message, user, nav_token)
        return
    await show_seller_start(message)


@router.message()
async def seller_fallback(message: Message, _state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user and str(user["status"]) == "active":
        await message.answer("Пожалуйста, выберите пункт меню.")
        await show_seller_menu(message, message.from_user.id)
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
