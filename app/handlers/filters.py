from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_config
from app.db import sqlite


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
