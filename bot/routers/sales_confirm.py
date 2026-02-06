from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.config import BUTTONS
from bot.db.repo import (
    confirm_sale,
    get_sale_by_id,
    list_unconfirmed_sales,
    log_audit,
)
from bot.services.time_utils import month_key_from_date

router = Router()


class ConfirmSaleState(StatesGroup):
    ask_month_year = State()
    choose_sale = State()


def _parse_month_year(value: str):
    parts = value.replace("/", " ").replace("-", " ").split()
    if len(parts) != 2:
        return None
    month, year = parts
    try:
        month = int(month)
        year = int(year)
    except ValueError:
        return None
    if not (1 <= month <= 12):
        return None
    return month, year


@router.message(F.text == BUTTONS["CONFIRM_SALE"])
async def confirm_sale_start(message: Message, state: FSMContext):
    await state.set_state(ConfirmSaleState.ask_month_year)
    await message.answer("Введите месяц и год (например: 01 2026)")


@router.message(ConfirmSaleState.ask_month_year)
async def confirm_sale_month(message: Message, state: FSMContext, session_factory, user):
    if not user.organization:
        await message.answer("Продажи доступны только после привязки к организации.")
        await state.clear()
        return
    parsed = _parse_month_year(message.text or "")
    if not parsed:
        await message.answer("Неверный формат. Используйте: MM YYYY")
        return
    month, year = parsed
    month_key = month_key_from_date(year, month)
    await state.update_data(month_key=month_key, offset=0)
    await message.answer("Ищу продажи...")
    await _send_sales_page(message, state, session_factory, user)


@router.message(ConfirmSaleState.choose_sale)
async def confirm_sale_choose(message: Message, state: FSMContext, session_factory, user):
    text = (message.text or "").strip()
    if text.lower() == "далее":
        data = await state.get_data()
        await state.update_data(offset=data.get("offset", 0) + 10)
        await _send_sales_page(message, state, session_factory, user)
        return
    if not text.isdigit():
        await message.answer("Введите ID продажи или 'Далее' для следующей страницы.")
        return
    sale_id = int(text)
    async with session_factory() as session:
        sale = await get_sale_by_id(session, sale_id)
        if not sale or sale.seller_inn != user.organization.inn:
            await message.answer("Продажа не найдена или недоступна.")
            return
        success = await confirm_sale(session, sale_id, user.id, user.org_id)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "CONFIRM_SALE"},
        )
    if success:
        await message.answer("Продажа успешно зафиксирована.")
    else:
        await message.answer("Продажа уже зафиксирована другим пользователем.")


async def _send_sales_page(message: Message, state: FSMContext, session_factory, user):
    data = await state.get_data()
    month_key = data.get("month_key")
    offset = data.get("offset", 0)
    async with session_factory() as session:
        sales = await list_unconfirmed_sales(
            session, user.organization.inn, month_key, limit=10, offset=offset
        )
    if not sales:
        await message.answer("Продаж больше нет.")
        await state.clear()
        return
    lines = []
    for sale in sales:
        lines.append(
            "\n".join(
                [
                    f"ID: {sale.id}",
                    f"Период: {sale.period}",
                    f"Тип операции: {sale.operation_type}",
                    f"Номенклатура: {sale.product_name}",
                    f"Объем товаров: {sale.volume_total}",
                    f"Продавец ИНН: {sale.seller_inn}",
                    f"Продавец: {sale.seller_name}",
                    f"Покупатель ИНН: {sale.buyer_inn}",
                    f"Покупатель: {sale.buyer_name}",
                ]
            )
        )
    await message.answer("\n\n".join(lines))
    await message.answer("Введите ID продажи для фиксации или 'Далее' для следующей страницы.")
    await state.set_state(ConfirmSaleState.choose_sale)
