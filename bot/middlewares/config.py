from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware

from bot.config import Config


class ConfigMiddleware(BaseMiddleware):
    def __init__(self, config: Config) -> None:
        self._config = config

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["config"] = self._config
        return await handler(event, data)
