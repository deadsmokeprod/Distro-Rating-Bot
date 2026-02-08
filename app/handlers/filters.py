from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_config
from app.db import sqlite


class ManagerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        return user_id in config.manager_ids


class SellerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        if user_id in config.manager_ids:
            return False
        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        return user is not None


class UnregisteredSellerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        user_id = event.from_user.id
        if user_id in config.manager_ids:
            return False
        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        return user is None


class NonManagerFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        config = get_config()
        return event.from_user.id not in config.manager_ids
