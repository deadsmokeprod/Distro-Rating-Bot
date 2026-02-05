from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.config import load_config
from bot.keyboards.menu import BUTTON_LABELS
from bot.services.access import is_allowed


class MenuAccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        if not event.from_user or not event.text:
            return await handler(event, data)
        if event.chat.type != "private":
            return await handler(event, data)
        label_to_key = {v: k for k, v in BUTTON_LABELS.items()}
        button_key = label_to_key.get(event.text)
        if not button_key:
            return await handler(event, data)
        user = data.get("db_user")
        if not user:
            return await handler(event, data)
        config = load_config()
        if not is_allowed(config.menu_config, user.role, button_key):
            await event.answer("Недостаточно прав.")
            return None
        return await handler(event, data)
