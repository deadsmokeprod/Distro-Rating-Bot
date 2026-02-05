from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message


class RegisteredGuardMiddleware(BaseMiddleware):
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
        if event.chat.type != "private":
            return await handler(event, data)
        if event.text and event.text.startswith("/start"):
            return await handler(event, data)
        if data.get("db_user") is None:
            await event.answer("Пожалуйста, сначала выполните /start и регистрацию.")
            return None
        return await handler(event, data)
