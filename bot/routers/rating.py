from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.config import BUTTONS, ROLE_ADMIN, ROLE_SUPER_ADMIN, Config
from bot.db.repo import (
    get_company_rating,
    get_personal_rating,
    list_admin_organizations,
    list_company_ratings,
    list_company_staff_ratings,
    log_audit,
)
from bot.services.excel_export import build_rating_excel
from bot.services.rating_service import format_decimal
from bot.services.time_utils import list_last_month_keys, month_key_from_date

router = Router()


class RatingExportState(StatesGroup):
    ask_month_year = State()


def _parse_month_year(value: str):
    parts = value.replace("/", " ").replace("-", " ").split()
    if len(parts) != 2:
        return None
    month, year = parts
    try:
        month = int(month)
        year = int(year)
    except ValueError:
        return None
    if not (1 <= month <= 12):
        return None
    return month, year


def _slice_around(items: List[Tuple[str, str, float]], key: str, size: int) -> List[Tuple]:
    if not items:
        return []
    try:
        idx = next(i for i, item in enumerate(items) if item[0] == key)
    except StopIteration:
        return items[:size]
    half = size // 2
    start = max(idx - half, 0)
    end = start + size
    if end > len(items):
        end = len(items)
        start = max(0, end - size)
    return items[start:end]


@router.message(F.text == BUTTONS["RATING_EXPORT"])
async def rating_export(message: Message, state: FSMContext, config: Config, session_factory, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(RatingExportState.ask_month_year)
    await message.answer("Введите месяц и год (например: 01 2026)")


@router.message(RatingExportState.ask_month_year)
async def rating_export_month(message: Message, state: FSMContext, session_factory, user):
    parsed = _parse_month_year(message.text or "")
    if not parsed:
        await message.answer("Неверный формат. Используйте: MM YYYY")
        return
    month, year = parsed
    month_key = month_key_from_date(year, month)
    async with session_factory() as session:
        ratings = await list_company_ratings(session, month_key)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "RATING_EXPORT"},
        )
    ratings_sorted = [(rating, inn, name) for inn, name, rating in ratings]
    export_path = Path("rating_export.xlsx")
    build_rating_excel(ratings_sorted, str(export_path))
    await message.answer_document(export_path)
    export_path.unlink(missing_ok=True)
    await state.clear()


@router.message(F.text == BUTTONS["MY_DISTRIBUTORS"])
async def my_distributors(message: Message, session_factory, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        return
    now = datetime.utcnow()
    month_key = now.strftime("%Y-%m")
    prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    async with session_factory() as session:
        orgs = await list_admin_organizations(session, user.tg_id)
        lines: List[str] = []
        for org in orgs:
            current = await get_company_rating(session, org.inn, month_key)
            previous = await get_company_rating(session, org.inn, prev_month)
            lines.append(
                f"{org.name} ({org.inn}) — {format_decimal(current)} (в прошлом {format_decimal(previous)})"
            )
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "MY_DISTRIBUTORS"},
        )
    await message.answer("\n".join(lines) or "Нет организаций.")


@router.message(F.text == BUTTONS["RATING_PERSONAL"])
async def rating_personal(message: Message, config: Config, session_factory, user):
    keys = list_last_month_keys(10, config.timezone)
    async with session_factory() as session:
        lines = []
        for key in keys:
            rating = await get_personal_rating(session, user.id, key)
            lines.append(f"{key}: {format_decimal(rating)}")
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "RATING_PERSONAL"},
        )
    await message.answer("\n".join(lines))


@router.message(F.text == BUTTONS["RATING_ORG"])
async def rating_org(message: Message, session_factory, user):
    if not user.org_id:
        await message.answer("Нет организации для отображения рейтинга.")
        return
    month_key = datetime.utcnow().strftime("%Y-%m")
    async with session_factory() as session:
        staff = await list_company_staff_ratings(session, user.org_id, month_key)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "RATING_ORG"},
        )
    lines = [f"{month_key}. Имя пользователя: {name}, Рейтинг: {format_decimal(value)}" for name, value in staff]
    await message.answer("\n".join(lines) or "Нет данных.")


@router.message(F.text == BUTTONS["RATING_ALL"])
async def rating_all(message: Message, session_factory, user):
    now = datetime.utcnow()
    month_key = now.strftime("%Y-%m")
    prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    async with session_factory() as session:
        ratings = await list_company_ratings(session, month_key)
        prev_ratings = {inn: rating for inn, _, rating in await list_company_ratings(session, prev_month)}
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "RATING_ALL"},
        )
    if not ratings:
        await message.answer("Нет данных.")
        return
    user_inn = user.organization.inn if user.organization else ""
    slice_ratings = _slice_around(ratings, user_inn, 10)
    lines: List[str] = []
    for index, (inn, name, rating) in enumerate(slice_ratings, start=1):
        prev = prev_ratings.get(inn, 0)
        if user.role in {ROLE_ADMIN, ROLE_SUPER_ADMIN} or inn == user_inn:
            line = (
                f"{index}. Наименование компании: {name}, ИНН:{inn}, "
                f"Рейтинг:{format_decimal(rating)}, а в прошлом было {format_decimal(prev)}"
            )
        else:
            line = (
                f"Компания-конкурент #{index}, Рейтинг: {format_decimal(rating)} "
                f"(в прошлом {format_decimal(prev)})"
            )
        if inn == user_inn:
            line = f"<b>{line}</b>"
        lines.append(line)
    await message.answer("\n".join(lines), parse_mode="HTML")
