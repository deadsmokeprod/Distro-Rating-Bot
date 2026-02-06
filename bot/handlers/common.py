from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.constants import BACK_BUTTON_TEXT, ROLE_SUPER_ADMIN
from bot.db.models import User
from bot.keyboards import main_menu
from bot.states import MenuStates


async def show_main_menu(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.set_state(MenuStates.main)
    await state.update_data(current_menu=MenuStates.main.state, previous_menu=None)
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu(user.role == ROLE_SUPER_ADMIN),
    )


async def go_back(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    config: Config,
) -> None:
    data = await state.get_data()
    prev = data.get("previous_menu")
    if prev == MenuStates.profile.state:
        from bot.handlers.profile import show_profile

        await show_profile(message, state, session, user)
        return
    if prev == MenuStates.confirm_menu.state:
        from bot.handlers.sales import show_confirm_menu

        await show_confirm_menu(message, state, user)
        return
    if prev == MenuStates.support_menu.state:
        from bot.handlers.support import show_support_menu

        await show_support_menu(message, state, user, config)
        return
    if prev == MenuStates.settings_menu.state:
        from bot.handlers.settings import show_settings_menu

        await show_settings_menu(message, state, session, user)
        return
    if prev == MenuStates.org_menu.state:
        from bot.handlers.settings import show_organizations_menu

        await show_organizations_menu(message, state, session, user)
        return
    await show_main_menu(message, state, user)


async def set_menu(state: FSMContext, menu_state: Any) -> None:
    data = await state.get_data()
    current = data.get("current_menu")
    await state.set_state(menu_state)
    await state.update_data(previous_menu=current, current_menu=menu_state.state)


def is_back(text: str) -> bool:
    return text.strip() == BACK_BUTTON_TEXT
