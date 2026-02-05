from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from decimal import Decimal
from pathlib import Path
from ..keyboards.menu import BUTTON_LABELS
from ..services.time_utils import get_recent_months, month_label, month_key, previous_month
from ..services.rating_service import company_rating, personal_rating, ranking_all_companies, ranking_users_in_org
from ..services.excel_export import export_company_ratings
from ..db.repo import log_audit, get_orgs_by_admin

router = Router()


class ExportState(StatesGroup):
    await_period = State()


@router.message(F.text == BUTTON_LABELS["RATING_EXPORT"])
async def rating_export(message: Message, state: FSMContext, db_user, session):
    await log_audit(session, message.from_user.id, db_user.role if db_user else None, "menu_click", {"button": "RATING_EXPORT"})
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Введите месяц и год в формате ММ.ГГГГ (например 01.2026):")
    await state.set_state(ExportState.await_period)


@router.message(ExportState.await_period)
async def export_period(message: Message, state: FSMContext, session):
    raw = message.text.strip()
    try:
        month, year = raw.split(".")
        month_key_value = f"{year}-{month}"
    except ValueError:
        await message.answer("Неверный формат. Введите ММ.ГГГГ")
        return
    ratings = await ranking_all_companies(session, month_key_value)
    rows = [(idx + 1, org.inn, org.name) for idx, (org, _) in enumerate(ratings)]
    file_path = Path("ratings_export.xlsx")
    export_company_ratings(rows, file_path)
    await message.answer_document(file_path)
    await state.clear()


@router.message(F.text == BUTTON_LABELS["MY_DISTRIBUTORS"])
async def my_distributors(message: Message, db_user, session, config):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "MY_DISTRIBUTORS"})
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    orgs = await get_orgs_by_admin(session, message.from_user.id)
    if not orgs:
        await message.answer("У вас нет зарегистрированных дистрибьютеров.")
        return
    current = get_recent_months(config.timezone, 1)[0]
    prev = previous_month(current)
    lines = []
    for org in orgs:
        current_rating = await company_rating(session, org.inn, month_key(current))
        prev_rating = await company_rating(session, org.inn, month_key(prev))
        lines.append(f"{org.name} ({org.inn}): {current_rating} (в прошлом {prev_rating})")
    await message.answer("\n".join(lines))


@router.message(F.text == BUTTON_LABELS["RATING_PERSONAL"])
async def rating_personal(message: Message, db_user, session, config):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "RATING_PERSONAL"})
    months = get_recent_months(config.timezone, 10)
    lines = []
    for month_dt in months:
        rating = await personal_rating(session, db_user.id, month_key(month_dt))
        lines.append(f"{month_label(month_dt)}: {rating}")
    await message.answer("\n".join(lines))


@router.message(F.text == BUTTON_LABELS["RATING_ORG"])
async def rating_org(message: Message, db_user, session, config):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "RATING_ORG"})
    if not db_user.org_id:
        await message.answer("Организация не найдена.")
        return
    months = get_recent_months(config.timezone, 1)
    month_dt = months[0]
    ratings = await ranking_users_in_org(session, db_user.org_id, month_key(month_dt))
    lines = [
        f"{month_label(month_dt)}. Имя пользователя: {user.full_name}, Рейтинг: {rating}"
        for user, rating in ratings
    ]
    await message.answer("\n".join(lines) if lines else "Нет данных")


@router.message(F.text == BUTTON_LABELS["RATING_ALL"])
async def rating_all(message: Message, db_user, session, config):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "RATING_ALL"})
    month_dt = get_recent_months(config.timezone, 1)[0]
    prev = previous_month(month_dt)
    ratings = await ranking_all_companies(session, month_key(month_dt))
    if not ratings:
        await message.answer("Нет данных для рейтинга.")
        return
    user_org = next((org for org, _ in ratings if db_user.org_id and org.id == db_user.org_id), None)
    if not user_org:
        top = ratings[:10]
    else:
        index = next(i for i, (org, _) in enumerate(ratings) if org.id == user_org.id)
        start = max(0, index - 5)
        top = ratings[start:start + 10]
    lines = []
    for idx, (org, rating) in enumerate(top, start=1):
        prev_rating = await company_rating(session, org.inn, month_key(prev))
        if db_user.role in {"MINI_ADMIN", "USER"} and (not db_user.org_id or org.id != db_user.org_id):
            lines.append(f"Компания-конкурент #{idx}, Рейтинг: {rating} (в прошлом {prev_rating})")
        else:
            lines.append(
                f"{idx}. Наименование компании: {org.name}, ИНН:{org.inn}, Рейтинг:{rating}, а в прошлом было {prev_rating}"
            )
    await message.answer("\n".join(lines))
