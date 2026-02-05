from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.db.engine import get_sessionmaker
from bot.db.repo import get_open_ticket_by_user
from bot.keyboards.menu import BUTTON_LABELS


class SupportLockMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        if not event.from_user or event.chat.type != "private":
            return await handler(event, data)

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            user = data.get("db_user")
            if not user:
                return await handler(event, data)
            ticket = await get_open_ticket_by_user(session, user.id)
        if not ticket:
            return await handler(event, data)
        blocked_labels = set(BUTTON_LABELS.values())
        allowed = {"Создать обращение в техподдержку", "✅ Обращение выполнено"}
        if event.text and event.text in blocked_labels and event.text not in allowed:
            await event.answer(
                "Сейчас вы общаетесь с поддержкой. Завершите диалог, чтобы продолжить."
            )
            return None
        return await handler(event, data)
