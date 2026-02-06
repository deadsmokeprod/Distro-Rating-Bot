from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import ChatTypeFilter
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.db.models import SupportTicket

logger = logging.getLogger(__name__)

router = Router()


@router.message(ChatTypeFilter(chat_type=["private"]))
async def relay_user_message(
    message: Message,
    session: AsyncSession,
    config: Config,
) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    support_group_id = config.support_group_id
    if support_group_id is None:
        return
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.tg_id == message.from_user.id,
            SupportTicket.status == "open",
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        return
    try:
        await message.bot.copy_message(
            chat_id=support_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=ticket.topic_id,
        )
    except Exception:
        logger.exception("Failed to relay user message")


@router.message()
async def relay_support_message(
    message: Message,
    session: AsyncSession,
    config: Config,
) -> None:
    support_group_id = config.support_group_id
    if support_group_id is None:
        return
    if message.chat.id != support_group_id:
        return
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.message_thread_id is None:
        return
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.topic_id == message.message_thread_id,
            SupportTicket.status == "open",
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        return
    try:
        await message.bot.copy_message(
            chat_id=ticket.tg_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("Failed to relay support message")
