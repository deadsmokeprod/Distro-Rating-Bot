from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.types import Message

from bot.db.engine import get_sessionmaker
from bot.db.repo import get_org_by_id
from bot.keyboards.menu import BUTTON_LABELS
from bot.services.audit import log_menu_click
from bot.services.rating_service import get_org_rating_with_previous, get_personal_rating_with_previous
from bot.services.time_utils import month_key_from_date, prev_month_key

router = Router()


@router.message(lambda m: m.text == BUTTON_LABELS["PROFILE"])
async def profile_handler(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "PROFILE")
    sessionmaker = get_sessionmaker()
    month_key = month_key_from_date(datetime.utcnow())
    prev_key = prev_month_key(month_key)
    org_rating = None
    org_prev = None
    org_name = None
    async with sessionmaker() as session:
        if db_user.org_id:
            org = await get_org_by_id(session, db_user.org_id)
            if org:
                org_name = org.name
                org_rating, org_prev = await get_org_rating_with_previous(session, org.inn, month_key, prev_key)
        personal, personal_prev = await get_personal_rating_with_previous(session, db_user.id, month_key, prev_key)
    payout_status = "УКАЗАНЫ" if db_user.payout_details else "НЕ УКАЗАНЫ"
    lines = [
        f"ID профиля: {db_user.tg_id}",
        f"Дата регистрации: {db_user.registered_at}",
        f"Реквизиты для выплат: {payout_status}",
    ]
    if org_name:
        lines.append(f"Рейтинг компании ({month_key}): {org_rating} (в прошлом {org_prev})")
    lines.append(f"Личный рейтинг ({month_key}): {personal} (в прошлом {personal_prev})")
    await message.answer("\n".join(lines))
