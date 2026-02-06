from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import MENU_CONFIRM_SALE, MENU_PROFILE, MENU_SETTINGS, MENU_SUPPORT
from bot.handlers.profile import show_profile
from bot.handlers.sales import show_confirm_menu
from bot.handlers.settings import show_settings_menu
from bot.config import Config
from bot.handlers.support import show_support_menu
from bot.services.users import get_user

router = Router()


@router.message(lambda message: message.text == MENU_PROFILE)
async def menu_profile(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await show_profile(message, state, session, user)


@router.message(lambda message: message.text == MENU_CONFIRM_SALE)
async def menu_confirm(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await show_confirm_menu(message, state, user)


@router.message(lambda message: message.text == MENU_SUPPORT)
async def menu_support(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await show_support_menu(message, state, user, config)


@router.message(lambda message: message.text == MENU_SETTINGS)
async def menu_settings(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await show_settings_menu(message, state, session, user)
