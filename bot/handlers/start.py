from __future__ import annotations

import logging

import bcrypt
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.constants import BACK_BUTTON_TEXT, ROLE_SELLER, ROLE_SUPER_ADMIN
from bot.db.models import Organization, User
from bot.handlers.common import show_main_menu
from bot.keyboards import back_menu
from bot.services.users import get_user
from bot.states import RegisterStates

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if user:
        await show_main_menu(message, state, user)
        return
    await state.set_state(RegisterStates.waiting_name)
    await message.answer(
        "Добро пожаловать! Введите ваше имя (2-64 символа):",
        reply_markup=back_menu(),
    )


@router.message(RegisterStates.waiting_name)
async def register_name(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer("Регистрация отменена. Введите /start, чтобы начать снова.")
        return
    if not (2 <= len(text) <= 64):
        await message.answer("Имя должно быть от 2 до 64 символов.")
        return
    await state.update_data(full_name=text)
    await state.set_state(RegisterStates.waiting_org_code)
    await message.answer(
        "Введите код организации:",
        reply_markup=back_menu(),
    )


@router.message(RegisterStates.waiting_org_code)
async def register_org_code(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    text = message.text.strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer("Регистрация отменена. Введите /start, чтобы начать снова.")
        return
    result = await session.execute(select(Organization))
    organizations = result.scalars().all()
    for org in organizations:
        if bcrypt.checkpw(text.encode(), org.access_hash.encode()):
            data = await state.get_data()
            full_name = data["full_name"]
            role = ROLE_SUPER_ADMIN if message.from_user.id in config.super_admin_ids else ROLE_SELLER
            user = User(
                tg_id=message.from_user.id,
                full_name=full_name,
                role=role,
                organization_inn=org.inn,
            )
            session.add(user)
            await session.commit()
            await show_main_menu(message, state, user)
            return
    await message.answer(
        "Код неверный, попробуйте ещё раз.",
        reply_markup=back_menu(),
    )
