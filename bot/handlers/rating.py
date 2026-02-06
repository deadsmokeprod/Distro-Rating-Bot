from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.constants import MENU_WORLD_RATING
from bot.services.rating import get_month_range, get_world_rating
from bot.services.users import get_user
from bot.states import MenuStates

router = Router()


@router.message(lambda message: message.text == MENU_WORLD_RATING)
async def world_rating(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await state.set_state(MenuStates.main)
    data = await state.get_data()
    await state.update_data(previous_menu=data.get("current_menu"), current_menu=MenuStates.main.state)
    rating = await get_world_rating(session, config.timezone)
    start, _ = get_month_range(config.timezone)
    month_label = f"{start:%Y-%m}"
    if not rating:
        await message.answer(
            f"Пока нет подтверждённых продаж для рейтинга за {month_label}."
        )
        return
    lines = [f"{idx}) {name} — {total:.2f} л" for idx, (name, total) in enumerate(rating, start=1)]
    await message.answer(
        "🌍 Мировой рейтинг продавцов — "
        f"{month_label}\n" + "\n".join(lines)
    )
