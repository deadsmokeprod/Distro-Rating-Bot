from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import Message

from bot.config import BUTTONS
from bot.db.repo import get_company_rating, get_personal_rating, log_audit
from bot.services.rating_service import format_decimal

router = Router()


@router.message(F.text == BUTTONS["PROFILE"])
async def profile(message: Message, session_factory, user):
    now = datetime.utcnow()
    month_key = now.strftime("%Y-%m")
    prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not user.organization:
        await message.answer("Профиль доступен только после привязки к организации.")
        return
    async with session_factory() as session:
        company_rating = await get_company_rating(session, user.organization.inn, month_key)
        company_prev = await get_company_rating(session, user.organization.inn, prev_month)
        personal_rating = await get_personal_rating(session, user.id, month_key)
        personal_prev = await get_personal_rating(session, user.id, prev_month)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "PROFILE"},
        )
    payout_status = "УКАЗАНЫ" if user.payout_details else "НЕ УКАЗАНЫ"
    lines = [
        f"ID профиля: {user.tg_id}",
        f"Дата регистрации: {user.registered_at.strftime('%Y-%m-%d')}",
        f"Рейтинг компании: {format_decimal(company_rating)} (в прошлом {format_decimal(company_prev)})",
        f"Личный рейтинг: {format_decimal(personal_rating)} (в прошлом {format_decimal(personal_prev)})",
        f"Реквизиты для выплат: {payout_status}",
    ]
    await message.answer("\n".join(lines))
