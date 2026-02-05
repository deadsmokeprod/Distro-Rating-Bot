from decimal import Decimal

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.keyboards.menu import main_menu
from bot.config import load_config
from bot.services.rating_service import (
    company_rankings,
    company_rating,
    org_members_ratings,
    user_rating,
)
from bot.services.time_utils import get_last_closed_month
from bot.services.excel_export import export_rating
from pathlib import Path
from bot.db.models import Organization


router = Router()


class ExportStates(StatesGroup):
    entering_month = State()


def _format_change(current: Decimal, previous: Decimal) -> str:
    return f"{current} (в прошлом {previous})"


@router.message(lambda message: message.text == "Рейтинг выгрузка")
async def rating_export(message: Message, state: FSMContext, user):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Введите месяц и год в формате YYYY-MM:")
    await state.set_state(ExportStates.entering_month)


@router.message(ExportStates.entering_month)
async def rating_export_month(message: Message, state: FSMContext, session: AsyncSession):
    month_key = message.text.strip()
    if len(month_key) != 7 or "-" not in month_key:
        await message.answer("Неверный формат. Пример: 2026-01")
        return
    rankings = await company_rankings(session, month_key)
    rows = [(idx, inn, name) for idx, (inn, name, _) in enumerate(rankings, start=1)]
    file_path = Path("rating_export.xlsx")
    export_rating(file_path, rows)
    await message.answer_document(file_path.open("rb"), caption=f"Рейтинг за {month_key}")
    file_path.unlink(missing_ok=True)
    await state.clear()


@router.message(lambda message: message.text == "Рейтинг моих дистрибьютеров")
async def rating_my_distributors(message: Message, session: AsyncSession, user):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    config = load_config()
    month_key, _, _ = get_last_closed_month(config.timezone)
    prev_key = _prev_month_key(month_key)
    result = await session.execute(
        select(Organization).where(Organization.created_by_admin_tg_id == user.tg_id)
    )
    orgs = result.scalars().all()
    if not orgs:
        await message.answer("Нет дистрибьютеров.")
        return
    lines = []
    for org in orgs:
        current = await company_rating(session, org.inn, month_key)
        previous = await company_rating(session, org.inn, prev_key)
        lines.append(f"{org.name} ({org.inn}): {current} (в прошлом {previous})")
    await message.answer("\n".join(lines))


@router.message(lambda message: message.text == "Рейтинг в этом месяце — личный")
async def rating_personal(message: Message, session: AsyncSession, user):
    config = load_config()
    month_key, _, _ = get_last_closed_month(config.timezone)
    month_keys = [month_key]
    for _ in range(9):
        month_keys.append(_prev_month_key(month_keys[-1]))
    lines = []
    for key in month_keys:
        rating = await user_rating(session, user.id, key)
        lines.append(f"{key}: {rating}")
    await message.answer("Личный рейтинг за последние 10 месяцев:\n" + "\n".join(lines))


@router.message(lambda message: message.text == "Рейтинг в этом месяце — в компании дистрибьютера")
async def rating_org(message: Message, session: AsyncSession, user):
    if not user.org_id:
        await message.answer("Организация не привязана.")
        return
    config = load_config()
    month_key, _, _ = get_last_closed_month(config.timezone)
    ratings = await org_members_ratings(session, user.org_id, month_key)
    lines = [f"{month_key}. Имя пользователя: {name}, Рейтинг: {total}" for name, total in ratings]
    await message.answer("\n".join(lines) or "Нет данных.")


@router.message(lambda message: message.text == "Рейтинг в этом месяце — все компании")
async def rating_all(message: Message, session: AsyncSession, user):
    config = load_config()
    month_key, _, _ = get_last_closed_month(config.timezone)
    rankings = await company_rankings(session, month_key)
    if not rankings:
        await message.answer("Нет данных.")
        return
    user_inn = None
    if user.org_id:
        result = await session.execute(select(Organization).where(Organization.id == user.org_id))
        org = result.scalar_one_or_none()
        if org:
            user_inn = org.inn
    lines = []
    display_rankings = rankings
    if user_inn:
        user_index = next((i for i, item in enumerate(rankings) if item[0] == user_inn), 0)
        start = max(user_index - 5, 0)
        end = min(start + 10, len(rankings))
        display_rankings = rankings[start:end]
        offset = start
    else:
        display_rankings = rankings[:10]
        offset = 0
    for idx, (inn, name, total) in enumerate(display_rankings, start=1 + offset):
        previous = await company_rating(session, inn, _prev_month_key(month_key))
        if user_inn == inn:
            lines.append(
                f"**{idx}. Наименование компании: {name}, ИНН:{inn}, Рейтинг:{total}, а в прошлом было {previous}**"
            )
        elif user.role in {"ADMIN", "SUPER_ADMIN"}:
            lines.append(
                f"{idx}. Наименование компании: {name}, ИНН:{inn}, Рейтинг:{total}, а в прошлом было {previous}"
            )
        else:
            lines.append(
                f"Компания-конкурент #{idx}, Рейтинг: {total} (в прошлом {previous})"
            )
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu(user.role))


def _prev_month_key(month_key: str) -> str:
    year, month = map(int, month_key.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"
