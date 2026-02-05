from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Awaitable
from ..db.repo import get_user_by_tg, update_last_seen


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        user = None
        if getattr(event, "from_user", None):
            session = data.get("session")
            if session:
                user = await get_user_by_tg(session, event.from_user.id)
                if user:
                    await update_last_seen(session, event.from_user.id)
        data["db_user"] = user
        return await handler(event, data)
