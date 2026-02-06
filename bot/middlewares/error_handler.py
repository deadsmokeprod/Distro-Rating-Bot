import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ErrorMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            self.logger.exception("Unhandled error")
            bot = data.get("bot")
            event_chat = getattr(event, "chat", None)
            if bot and event_chat:
                try:
                    await bot.send_message(
                        chat_id=event_chat.id,
                        text="⚠️ Ошибка. Попробуйте ещё раз. Если повторяется — напишите в поддержку.",
                    )
                except Exception:
                    self.logger.exception("Failed to notify user about error")
            return None
