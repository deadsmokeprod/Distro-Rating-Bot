from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.routers.start import RegistrationStates


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type == "private":
            user = data.get("user")
            if not user:
                state = data.get("state")
                current_state = await state.get_state() if state else None
                if current_state and "RegistrationStates" in current_state:
                    return await handler(event, data)
                if event.text and event.text.startswith("/start"):
                    return await handler(event, data)
                await event.answer("Пожалуйста, сначала выполните /start для регистрации.")
                return None
        return await handler(event, data)
