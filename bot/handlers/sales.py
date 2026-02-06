from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import CONFIRM_BY_NUMBER, CONFIRM_SHOW_UNCONFIRMED
from bot.db.models import ErpSale, SaleConfirmation, User
from bot.handlers.common import is_back, set_menu
from bot.keyboards import confirm_menu
from bot.services.users import get_user
from bot.states import ConfirmStates, MenuStates

router = Router()


async def show_confirm_menu(message: Message, state: FSMContext, user: User) -> None:
    await set_menu(state, MenuStates.confirm_menu)
    await message.answer("Подтверждение продаж:", reply_markup=confirm_menu())


@router.message(lambda message: message.text == CONFIRM_SHOW_UNCONFIRMED)
async def show_unconfirmed(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    subquery = select(SaleConfirmation.sale_id).where(SaleConfirmation.sale_id == ErpSale.id)
    stmt = (
        select(ErpSale)
        .where(ErpSale.seller_inn == user.organization_inn)
        .where(~exists(subquery))
        .order_by(ErpSale.doc_date.desc())
        .limit(10)
    )
    result = await session.execute(stmt)
    sales = result.scalars().all()
    if not sales:
        await message.answer("Нет неподтверждённых продаж.")
        return
    lines = [
        f"{sale.id} | {sale.doc_date} | {sale.buyer_name or 'Без контрагента'} | {sale.volume_total_l} л"
        for sale in sales
    ]
    await message.answer("\n".join(lines))


@router.message(lambda message: message.text == CONFIRM_BY_NUMBER)
async def confirm_by_number_prompt(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await state.set_state(ConfirmStates.confirm_by_number)
    await message.answer("Введите номер продажи (sale_id):", reply_markup=confirm_menu())


@router.message(ConfirmStates.confirm_by_number)
async def confirm_by_number_process(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    text = message.text.strip()
    if is_back(text):
        await show_confirm_menu(message, state, user)
        return
    if not text.isdigit():
        await message.answer("Введите корректный номер продажи.")
        return
    sale_id = int(text)
    sale = await session.get(ErpSale, sale_id)
    if not sale:
        await message.answer("Не найдено. Проверь номер.")
        return
    if sale.seller_inn != user.organization_inn:
        await message.answer("Эта продажа относится к другой организации.")
        return
    exists_stmt = select(SaleConfirmation).where(SaleConfirmation.sale_id == sale_id)
    confirmation = await session.execute(exists_stmt)
    if confirmation.scalar_one_or_none():
        await message.answer("Эта продажа уже подтверждена.")
        return
    session.add(SaleConfirmation(sale_id=sale_id, tg_id=user.tg_id))
    await session.commit()
    await message.answer("✅ Продажа подтверждена и учтена в рейтинге.")

