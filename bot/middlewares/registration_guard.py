from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Callable, Awaitable
from aiogram.fsm.context import FSMContext


class RegistrationGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        handler_ref = data.get("handler")
        if handler_ref and handler_ref.flags.get("allow_unauth"):
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)
        if data.get("db_user"):
            return await handler(event, data)
        state: FSMContext | None = data.get("state")
        if state:
            current = await state.get_state()
            if current:
                return await handler(event, data)
        await event.answer("Сначала выполните /start для регистрации.")
        return None
