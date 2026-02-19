from __future__ import annotations

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_config
from app.db import sqlite
from app.utils.inline_menu import get_active_inline_menu_message_id
from app.utils.nav_history import clear_history

logger = logging.getLogger(__name__)


class ManagerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        return user_id in config.manager_ids or user_id in config.admin_ids


class SellerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        if user_id in config.manager_ids or user_id in config.admin_ids:
            return False
        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        return user is not None and str(user["status"]) == "active"


class UnregisteredSellerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        if user_id in config.manager_ids or user_id in config.admin_ids:
            return False
        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        return user is None or str(user["status"]) != "active"


class NonManagerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        return user_id not in config.manager_ids and user_id not in config.admin_ids


class PrivateChatFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        message: Message | None
        if isinstance(event, CallbackQuery):
            message = event.message
        else:
            message = event
        if message is None or message.chat is None:
            return False
        return str(message.chat.type) == "private"


class ActiveInlineMenuFilter(BaseFilter):
    async def __call__(self, event: CallbackQuery) -> bool:
        if event.message is None or event.from_user is None:
            return True
        active_message_id = await get_active_inline_menu_message_id(
            int(event.message.chat.id),
            int(event.from_user.id),
        )
        if active_message_id is None:
            return True
        is_active = int(event.message.message_id) == active_message_id
        if is_active:
            return True
        try:
            await event.answer("Меню обновилось. Показываю актуальный экран.", show_alert=False)
            config = get_config()
            user_id = int(event.from_user.id)
            await clear_history(user_id)
            if user_id in config.manager_ids or user_id in config.admin_ids:
                from app.keyboards.manager import manager_main_menu

                await event.message.answer(
                    "Открыл актуальное меню.",
                    reply_markup=manager_main_menu(is_admin_view=user_id in config.admin_ids),
                )
            else:
                from app.keyboards.seller import seller_main_menu

                user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
                role = str(user["role"]) if user and str(user["status"]) == "active" else "seller"
                await event.message.answer(
                    "Открыл актуальное меню.",
                    reply_markup=seller_main_menu(role=role),
                )
        except Exception:
            logger.exception("Failed to process stale inline callback fallback")
            try:
                await event.answer("Меню устарело. Откройте раздел заново.", show_alert=False)
            except Exception:
                logger.debug("Failed to answer stale callback")
        return False
