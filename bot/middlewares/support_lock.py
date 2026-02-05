from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Callable, Awaitable
from ..db.repo import get_support_ticket_by_user


class SupportLockMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        handler_ref = data.get("handler")
        if handler_ref and handler_ref.flags.get("allow_support_actions"):
            return await handler(event, data)
        if not getattr(event, "from_user", None):
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)
        user = data.get("db_user")
        if not user:
            return await handler(event, data)
        session = data.get("session")
        if not session:
            return await handler(event, data)
        ticket = await get_support_ticket_by_user(session, user.id)
        if ticket:
            await event.answer("Сейчас вы общаетесь с поддержкой. Завершите диалог, чтобы продолжить.")
            return None
        return await handler(event, data)
