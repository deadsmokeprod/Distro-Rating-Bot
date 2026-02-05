from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.db.repo import get_user_by_tg_id, update_last_seen


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            session = data["session"]
            user = await get_user_by_tg_id(session, event.from_user.id)
            if user:
                await update_last_seen(session, user.id)
                data["user"] = user
        return await handler(event, data)
