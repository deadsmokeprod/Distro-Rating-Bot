from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Awaitable


class DBSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker):
        self.sessionmaker = sessionmaker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        async with self.sessionmaker() as session:
            data["session"] = session
            return await handler(event, data)
