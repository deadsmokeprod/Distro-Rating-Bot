from __future__ import annotations

from aiogram.types import Message

from bot.db.engine import get_sessionmaker
from bot.db.repo import add_audit_log


async def log_menu_click(message: Message, role: str | None, button: str) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await add_audit_log(
            session,
            message.from_user.id if message.from_user else None,
            role,
            "menu_click",
            {"button": button},
        )
