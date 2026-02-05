from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.config import load_config
from bot.db.engine import get_sessionmaker
from bot.db.repo import get_user_by_tg_id, update_last_seen


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        if not event.from_user:
            return await handler(event, data)
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            user = await get_user_by_tg_id(session, event.from_user.id)
            data["db_user"] = user
            if user:
                await update_last_seen(session, event.from_user.id)
        return await handler(event, data)
