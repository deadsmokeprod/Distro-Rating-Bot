from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.db.repo import get_user_by_tg


class AuthMiddleware(BaseMiddleware):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[Message, dict], Awaitable[Any]],
        event: Message,
        data: dict,
    ) -> Any:
        allow = data.get("allow_unauthorized")
        if allow:
            return await handler(event, data)
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)
        async with self.session_factory() as session:
            user = await get_user_by_tg(session, event.from_user.id)
        if not user:
            await event.answer("Сначала зарегистрируйтесь через /start")
            return None
        data["user"] = user
        return await handler(event, data)
