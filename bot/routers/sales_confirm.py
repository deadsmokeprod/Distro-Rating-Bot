from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.repo import confirm_sale, get_org_by_id, get_unconfirmed_sales


router = Router()


class SaleConfirmStates(StatesGroup):
    choosing_month = State()
    choosing_sale = State()


@router.message(lambda message: message.text == "Зафиксировать продажу")
async def start_confirm(message: Message, state: FSMContext):
    await message.answer("Введите месяц и год в формате YYYY-MM:")
    await state.set_state(SaleConfirmStates.choosing_month)


@router.message(SaleConfirmStates.choosing_month)
async def enter_month(message: Message, state: FSMContext, session: AsyncSession, user):
    month_key = message.text.strip()
    if len(month_key) != 7 or "-" not in month_key:
        await message.answer("Неверный формат. Пример: 2026-01")
        return
    org = await get_org_by_id(session, user.org_id) if user.org_id else None
    if not org:
        await message.answer("Организация не привязана.")
        await state.clear()
        return
    sales = await get_unconfirmed_sales(session, org.inn, month_key, limit=10)
    if not sales:
        await message.answer("Нет доступных продаж для фиксации.")
        await state.clear()
        return
    lines = []
    for sale in sales:
        lines.append(
            f"{sale.id}) Период: {sale.period} | Тип: {sale.operation_type} | Номенклатура: {sale.product_name} | "
            f"Объем: {sale.volume_total} | Продавец ИНН: {sale.seller_inn} | Продавец: {sale.seller_name} | "
            f"Покупатель ИНН: {sale.buyer_inn} | Покупатель: {sale.buyer_name}"
        )
    await message.answer("\n".join(lines))
    await message.answer("Введите ID строки для фиксации:")
    await state.set_state(SaleConfirmStates.choosing_sale)
    await state.update_data(month_key=month_key)


@router.message(SaleConfirmStates.choosing_sale)
async def confirm_sale_handler(message: Message, state: FSMContext, session: AsyncSession, user):
    try:
        sale_id = int(message.text.strip())
    except ValueError:
        await message.answer("Введите числовой ID.")
        return
    try:
        await confirm_sale(session, sale_id, user.id, user.org_id)
        await message.answer("Продажа зафиксирована.")
    except IntegrityError:
        await session.rollback()
        await message.answer("Эта продажа уже зафиксирована другим пользователем.")
    await state.clear()
