from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError
from ..keyboards.menu import BUTTON_LABELS
from ..services.time_utils import month_key, month_label
from ..db.repo import get_sales_for_org, confirm_sale, log_audit, get_org_by_id

router = Router()


class ConfirmState(StatesGroup):
    await_period = State()
    await_sale_id = State()


@router.message(F.text == BUTTON_LABELS["CONFIRM_SALE"])
async def start_confirm(message: Message, state: FSMContext, db_user, session):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "CONFIRM_SALE"})
    await message.answer("Введите месяц и год в формате ММ.ГГГГ (например 01.2026):")
    await state.set_state(ConfirmState.await_period)


@router.message(ConfirmState.await_period)
async def confirm_period(message: Message, state: FSMContext, db_user, session):
    raw = message.text.strip()
    try:
        month, year = raw.split(".")
        month_key_value = f"{year}-{month}"
    except ValueError:
        await message.answer("Неверный формат. Введите ММ.ГГГГ")
        return
    await state.update_data(month_key=month_key_value, offset=0)
    await _send_sales_page(message, state, db_user, session)


async def _send_sales_page(message: Message, state: FSMContext, db_user, session):
    data = await state.get_data()
    month_key_value = data["month_key"]
    offset = data.get("offset", 0)
    if not db_user.org_id:
        await message.answer("Организация не найдена.")
        await state.clear()
        return
    org = await get_org_by_id(session, db_user.org_id)
    if not org:
        await message.answer("Организация не найдена.")
        await state.clear()
        return
    sales = await get_sales_for_org(session, org.inn, month_key_value, limit=15, offset=offset)
    if not sales:
        await message.answer("Нет доступных продаж.")
        await state.clear()
        return
    lines = []
    for sale in sales:
        lines.append(
            f"ID {sale.id} | {sale.period} | {sale.operation_type} | {sale.product_name} | "
            f"{sale.volume_total} | {sale.seller_inn} | {sale.seller_name} | {sale.buyer_inn} | {sale.buyer_name}"
        )
    lines.append("Введите ID строки для фиксации или 'далее' для следующей страницы.")
    await message.answer("\n".join(lines))
    await state.set_state(ConfirmState.await_sale_id)


@router.message(ConfirmState.await_sale_id)
async def confirm_sale_id(message: Message, state: FSMContext, db_user, session):
    text = message.text.strip().lower()
    data = await state.get_data()
    if text == "далее":
        await state.update_data(offset=data.get("offset", 0) + 15)
        await _send_sales_page(message, state, db_user, session)
        return
    if not text.isdigit():
        await message.answer("Введите числовой ID или 'далее'.")
        return
    sale_id = int(text)
    try:
        await confirm_sale(session, sale_id, db_user.id, db_user.org_id)
    except IntegrityError:
        await message.answer("Эта продажа уже зафиксирована другим пользователем.")
        await state.clear()
        return
    await message.answer("Продажа зафиксирована.")
    await state.clear()
