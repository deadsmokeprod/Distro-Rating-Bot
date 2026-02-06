from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import BACK_BUTTON_TEXT
from bot.config import Config
from bot.handlers.common import go_back
from bot.services.users import get_user

router = Router()


@router.message(lambda message: message.text == BACK_BUTTON_TEXT)
async def handle_back(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await go_back(message, state, session, user, config)
