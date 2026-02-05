from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import load_config
from bot.db.repo import get_org_by_id
from bot.services.rating_service import company_rating, user_rating
from bot.services.time_utils import get_last_closed_month


router = Router()


def _prev_month_key(month_key: str) -> str:
    year, month = map(int, month_key.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


@router.message(lambda message: message.text == "Профиль и данные")
async def profile_info(message: Message, session: AsyncSession, user):
    config = load_config()
    month_key, _, _ = get_last_closed_month(config.timezone)
    prev_key = _prev_month_key(month_key)
    org_rating = "Нет данных"
    org_prev = "Нет данных"
    if user.org_id:
        org = await get_org_by_id(session, user.org_id)
        if org:
            org_rating = await company_rating(session, org.inn, month_key)
            org_prev = await company_rating(session, org.inn, prev_key)
    personal_rating = await user_rating(session, user.id, month_key)
    personal_prev = await user_rating(session, user.id, prev_key)
    requisites_status = "УКАЗАНЫ" if user.payout_requisites else "НЕ УКАЗАНЫ"
    lines = [
        f"ID профиля: {user.tg_id}",
        f"Дата регистрации: {user.registered_at}",
        f"Рейтинг компании: {org_rating} (в прошлом {org_prev})",
        f"Личный рейтинг: {personal_rating} (в прошлом {personal_prev})",
        f"Реквизиты для выплат: {requisites_status}",
    ]
    await message.answer("\n".join(lines))
