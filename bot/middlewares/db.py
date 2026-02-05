from aiogram import BaseMiddleware

from bot.db.engine import SessionLocal


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
