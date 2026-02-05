from aiogram import Router, F
from aiogram.types import Message
from ..keyboards.menu import BUTTON_LABELS
from ..services.time_utils import get_recent_months, month_key, previous_month
from ..services.rating_service import company_rating, personal_rating
from ..db.repo import log_audit, get_org_by_id

router = Router()


@router.message(F.text == BUTTON_LABELS["PROFILE"])
async def profile(message: Message, db_user, session, config):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "PROFILE"})
    current = get_recent_months(config.timezone, 1)[0]
    prev = previous_month(current)
    org_rating = "0"
    prev_org = "0"
    if db_user.org_id:
        org = await get_org_by_id(session, db_user.org_id)
        if org:
            org_rating = str(await company_rating(session, org.inn, month_key(current)))
            prev_org = str(await company_rating(session, org.inn, month_key(prev)))
    personal = str(await personal_rating(session, db_user.id, month_key(current)))
    prev_personal = str(await personal_rating(session, db_user.id, month_key(prev)))
    payout_status = "УКАЗАНЫ" if db_user.payout_details else "НЕ УКАЗАНЫ"
    lines = [
        f"ID профиля: {db_user.tg_id}",
        f"Дата регистрации: {db_user.registered_at}",
        f"Рейтинг компании: {org_rating} (в прошлом {prev_org})",
        f"Личный рейтинг: {personal} (в прошлом {prev_personal})",
        f"Реквизиты для выплат: {payout_status}",
    ]
    await message.answer("\n".join(lines))
