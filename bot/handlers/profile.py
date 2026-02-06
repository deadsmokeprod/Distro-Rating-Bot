from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import PROFILE_EDIT_NAME
from bot.db.models import Organization, User
from bot.handlers.common import is_back, set_menu
from bot.keyboards import profile_menu
from bot.services.users import get_user
from bot.states import MenuStates, ProfileStates

router = Router()


async def show_profile(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    org = await session.get(Organization, user.organization_inn)
    org_label = f"{org.name} ({org.inn})" if org else user.organization_inn
    await set_menu(state, MenuStates.profile)
    await message.answer(
        f"Имя: {user.full_name}\nРоль: {user.role}\nОрганизация: {org_label}",
        reply_markup=profile_menu(),
    )


@router.message(lambda message: message.text == PROFILE_EDIT_NAME)
async def profile_edit_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await state.set_state(ProfileStates.edit_name)
    await message.answer("Введите новое имя (2-64 символа):", reply_markup=profile_menu())


@router.message(ProfileStates.edit_name)
async def profile_edit_name_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    text = message.text.strip()
    if is_back(text):
        await show_profile(message, state, session, user)
        return
    if not (2 <= len(text) <= 64):
        await message.answer("Имя должно быть от 2 до 64 символов.")
        return
    user.full_name = text
    await session.commit()
    await show_profile(message, state, session, user)
