from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.db.engine import get_sessionmaker
from bot.db.repo import confirm_sale, get_org_by_id, list_sales_for_confirmation
from bot.keyboards.menu import BUTTON_LABELS
from bot.services.audit import log_menu_click

router = Router()


class ConfirmState(StatesGroup):
    input_month = State()
    choose_sale = State()


@router.message(lambda m: m.text == BUTTON_LABELS["CONFIRM_SALE"])
async def confirm_sale_start(message: Message, state: FSMContext, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "CONFIRM_SALE")
    if not db_user.org_id:
        await message.answer("Организация не привязана.")
        return
    await message.answer("Введите месяц и год в формате MM.YYYY")
    await state.set_state(ConfirmState.input_month)


@router.message(ConfirmState.input_month)
async def confirm_sale_month(message: Message, state: FSMContext, db_user) -> None:
    text = (message.text or "").strip()
    try:
        month, year = text.split(".")
        month_key = f"{year}-{month.zfill(2)}"
    except ValueError:
        await message.answer("Неверный формат. Введите MM.YYYY")
        return
    await state.update_data(month_key=month_key, offset=0)
    await _send_sales_page(message, state, db_user)
    await state.set_state(ConfirmState.choose_sale)


@router.message(ConfirmState.choose_sale)
async def confirm_sale_choose(message: Message, state: FSMContext, db_user) -> None:
    text = (message.text or "").strip().lower()
    if text == "далее":
        data = await state.get_data()
        offset = data.get("offset", 0) + 10
        await state.update_data(offset=offset)
        await _send_sales_page(message, state, db_user)
        return
    if not text.isdigit():
        await message.answer("Введите ID продажи или 'Далее' для следующей страницы.")
        return
    sale_id = int(text)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_id(session, db_user.org_id)
        success = await confirm_sale(session, sale_id, db_user.id, db_user.org_id)
    if success:
        await message.answer("Продажа зафиксирована.")
    else:
        await message.answer("Эта продажа уже была зафиксирована другим пользователем.")


async def _send_sales_page(message: Message, state: FSMContext, db_user) -> None:
    data = await state.get_data()
    month_key = data.get("month_key")
    offset = data.get("offset", 0)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_id(session, db_user.org_id)
        if not org:
            await message.answer("Организация не найдена.")
            return
        sales = await list_sales_for_confirmation(session, org.inn, month_key, limit=10, offset=offset)
    if not sales:
        await message.answer("Нет доступных продаж для фиксации.")
        return
    lines = [
        "Доступные продажи (введите ID продажи или 'Далее'):",
    ]
    for sale in sales:
        lines.append(
            f"{sale.id}) Период: {sale.period}, Тип: {sale.operation_type}, Номенклатура: {sale.product_name}, "
            f"Объем: {sale.volume_total}, Продавец ИНН: {sale.seller_inn}, Продавец: {sale.seller_name}, "
            f"Покупатель ИНН: {sale.buyer_inn}, Покупатель: {sale.buyer_name}"
        )
    await message.answer("\n".join(lines))
