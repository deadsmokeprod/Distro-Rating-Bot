from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.db.repo import log_audit
from bot.keyboards.menu import BUTTON_LABELS


class MenuLoggerMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.reverse = {label: key for key, label in BUTTON_LABELS.items()}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            button_key = self.reverse.get(event.text)
            if button_key:
                user = data.get("user")
                session = data["session"]
                await log_audit(
                    session,
                    tg_id=event.from_user.id,
                    role=user.role if user else None,
                    action="menu_click",
                    meta={"button": button_key},
                )
        return await handler(event, data)
