from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.db.engine import get_sessionmaker
from bot.db.repo import get_org_by_id, list_orgs_created_by_admin
from bot.keyboards.menu import BUTTON_LABELS
from bot.services.audit import log_menu_click
from bot.services.excel_export import export_ratings
from bot.services.rating_service import (
    build_org_ranking,
    build_personal_ranking_for_org,
    get_org_rating_with_previous,
    get_personal_rating_with_previous,
)
from bot.services.time_utils import month_key_from_date, prev_month_key

router = Router()


class ExportState(StatesGroup):
    input_month = State()


def _parse_month(text: str) -> tuple[str, str] | None:
    try:
        month, year = text.strip().split(".")
        month = month.zfill(2)
        year = year.strip()
        return year, month
    except ValueError:
        return None


@router.message(lambda m: m.text == BUTTON_LABELS["RATING_EXPORT"])
async def rating_export_start(message: Message, state: FSMContext, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "RATING_EXPORT")
    await state.set_state(ExportState.input_month)
    await message.answer("Введите месяц и год в формате MM.YYYY")


@router.message(ExportState.input_month)
async def rating_export_finish(message: Message, state: FSMContext) -> None:
    parsed = _parse_month(message.text or "")
    if not parsed:
        await message.answer("Неверный формат. Введите месяц и год в формате MM.YYYY")
        return
    year, month = parsed
    month_key = f"{year}-{month}"
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = await build_org_ranking(session, month_key)
        export_rows = [(idx + 1, inn, name) for idx, (inn, name, _) in enumerate(rows)]
    path = Path("exports")
    path.mkdir(exist_ok=True)
    file_path = path / f"rating_{month_key}.xlsx"
    export_ratings(file_path, export_rows)
    await message.answer_document(file_path.open("rb"))
    await state.clear()


@router.message(lambda m: m.text == BUTTON_LABELS["MY_DISTRIBUTORS"])
async def rating_my_distributors(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "MY_DISTRIBUTORS")
    sessionmaker = get_sessionmaker()
    month_key = month_key_from_date(datetime.utcnow())
    prev_key = prev_month_key(month_key)
    async with sessionmaker() as session:
        orgs = await list_orgs_created_by_admin(session, message.from_user.id)
        lines = []
        for org in orgs:
            current, prev = await get_org_rating_with_previous(session, org.inn, month_key, prev_key)
            lines.append(f"{org.name} ({org.inn}): {current} (в прошлом {prev})")
    await message.answer("\n".join(lines) if lines else "Нет дистрибьютеров.")


@router.message(lambda m: m.text == BUTTON_LABELS["RATING_PERSONAL"])
async def rating_personal(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "RATING_PERSONAL")
    sessionmaker = get_sessionmaker()
    now = datetime.utcnow()
    lines = []
    async with sessionmaker() as session:
        for i in range(10):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            month_key = f"{year}-{str(month).zfill(2)}"
            prev_key = prev_month_key(month_key)
            current, prev = await get_personal_rating_with_previous(session, db_user.id, month_key, prev_key)
            lines.append(f"{month_key}: {current} (в прошлом {prev})")
    await message.answer("\n".join(lines))


@router.message(lambda m: m.text == BUTTON_LABELS["RATING_ORG"])
async def rating_org(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "RATING_ORG")
    if not db_user.org_id:
        await message.answer("Организация не привязана.")
        return
    sessionmaker = get_sessionmaker()
    month_key = month_key_from_date(datetime.utcnow())
    async with sessionmaker() as session:
        data = await build_personal_ranking_for_org(session, db_user.org_id, month_key)
    if not data:
        await message.answer("Нет данных.")
        return
    lines = [f"{month_key}. Имя пользователя: {name}, Рейтинг: {rating}" for name, rating in data]
    await message.answer("\n".join(lines))


@router.message(lambda m: m.text == BUTTON_LABELS["RATING_ALL"])
async def rating_all(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "RATING_ALL")
    sessionmaker = get_sessionmaker()
    month_key = month_key_from_date(datetime.utcnow())
    prev_key = prev_month_key(month_key)
    async with sessionmaker() as session:
        rankings = await build_org_ranking(session, month_key)
        prev_rankings = await build_org_ranking(session, prev_key)
        org_inn = None
        if db_user.org_id:
            org = await get_org_by_id(session, db_user.org_id)
            org_inn = org.inn if org else None
    prev_map = {inn: rating for inn, _, rating in prev_rankings}
    index = 0
    if org_inn:
        for idx, (inn, _, _) in enumerate(rankings):
            if inn == org_inn:
                index = idx
                break
    start = max(0, index - 5)
    end = min(len(rankings), start + 10)
    slice_rankings = rankings[start:end]
    lines = []
    for i, (inn, name, rating) in enumerate(slice_rankings, start=start + 1):
        prev = prev_map.get(inn, Decimal("0"))
        if db_user.role in {"MINI_ADMIN", "USER"} and org_inn and inn != org_inn:
            label = f"Компания-конкурент #{i}"
            lines.append(f"{label}, Рейтинг: {rating} (в прошлом {prev})")
        else:
            line = f"{i}. Наименование компании: {name}, ИНН:{inn}, Рейтинг:{rating}, а в прошлом было {prev}"
            if org_inn and inn == org_inn:
                line = f"<b>{line}</b>"
            lines.append(line)
    await message.answer("\n".join(lines) if lines else "Нет данных.", parse_mode="HTML")
