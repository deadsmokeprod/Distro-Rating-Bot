from __future__ import annotations

import logging

from aiogram import Bot
import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SupportTicket

logger = logging.getLogger(__name__)


async def get_open_ticket(session: AsyncSession, tg_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.tg_id == tg_id,
            SupportTicket.status == "open",
        )
    )
    return result.scalar_one_or_none()


async def create_ticket(session: AsyncSession, tg_id: int, topic_id: int) -> SupportTicket:
    ticket = SupportTicket(tg_id=tg_id, topic_id=topic_id, status="open")
    session.add(ticket)
    await session.commit()
    return ticket


async def close_ticket(session: AsyncSession, tg_id: int) -> bool:
    ticket = await get_open_ticket(session, tg_id)
    if not ticket:
        return False
    await session.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket.id)
        .values(status="closed", closed_at=dt.datetime.utcnow())
    )
    await session.commit()
    return True


async def forward_to_support(bot: Bot, group_id: int, topic_id: int, message) -> None:
    if message.from_user and message.from_user.is_bot:
        return
    try:
        await bot.send_message(
            chat_id=group_id,
            message_thread_id=topic_id,
            text=f"{message.from_user.full_name}: {message.text}",
        )
    except Exception:
        logger.exception("Failed to forward message to support")


async def forward_to_user(bot: Bot, user_id: int, message) -> None:
    if message.from_user and message.from_user.is_bot:
        return
    try:
        await bot.send_message(chat_id=user_id, text=message.text or "")
    except Exception:
        logger.exception("Failed to forward message to user")
