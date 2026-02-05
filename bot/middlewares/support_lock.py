from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.db.repo import get_support_ticket_by_user
from bot.keyboards.menu import BUTTON_LABELS, SETTINGS_BUTTONS


class SupportLockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type == "private":
            user = data.get("user")
            if user:
                session = data["session"]
                ticket = await get_support_ticket_by_user(session, user.id)
                if ticket and event.text not in {"✅ Обращение выполнено"}:
                    blocked = set(BUTTON_LABELS.values()) | set(SETTINGS_BUTTONS.values())
                    if event.text not in blocked:
                        return await handler(event, data)
                    state = data.get("state")
                    if state:
                        current_state = await state.get_state()
                        if current_state and "SupportStates" in current_state:
                            return await handler(event, data)
                    await event.answer(
                        "Сейчас вы общаетесь с поддержкой. Завершите диалог, чтобы продолжить."
                    )
                    return None
        return await handler(event, data)
