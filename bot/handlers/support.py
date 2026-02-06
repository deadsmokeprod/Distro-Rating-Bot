from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.constants import SUPPORT_CLOSE, SUPPORT_CREATE
from bot.db.models import SupportTicket, User
from bot.handlers.common import set_menu, show_main_menu
from bot.keyboards import support_menu
from bot.services.users import get_user
from bot.states import MenuStates

logger = logging.getLogger(__name__)

router = Router()


async def show_support_menu(message: Message, state: FSMContext, user: User, config: Config) -> None:
    if config.support_group_id is None:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        await show_main_menu(message, state, user)
        return
    await set_menu(state, MenuStates.support_menu)
    await message.answer("Поддержка:", reply_markup=support_menu())


@router.message(lambda message: message.text == SUPPORT_CREATE)
async def support_create(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    support_group_id = config.support_group_id
    if support_group_id is None:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.tg_id == user.tg_id,
            SupportTicket.status == "open",
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket:
        await message.answer("У вас уже есть открытое обращение.")
        return
    topic = await message.bot.create_forum_topic(
        chat_id=support_group_id,
        name=f"{user.full_name} | {user.tg_id}",
    )
    new_ticket = SupportTicket(tg_id=user.tg_id, topic_id=topic.message_thread_id, status="open")
    session.add(new_ticket)
    await session.commit()
    await message.answer("Обращение создано. Опишите проблему одним сообщением или несколькими.")


@router.message(lambda message: message.text == SUPPORT_CLOSE)
async def support_close(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    support_group_id = config.support_group_id
    if support_group_id is None:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.tg_id == user.tg_id,
            SupportTicket.status == "open",
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        await message.answer("Открытых обращений нет.")
        return
    ticket.status = "closed"
    ticket.closed_at = datetime.utcnow()
    await session.commit()
    try:
        await message.bot.send_message(
            chat_id=support_group_id,
            message_thread_id=ticket.topic_id,
            text="Обращение закрыто пользователем.",
        )
    except Exception:
        logger.exception("Failed to notify support topic")
    await message.answer("Обращение закрыто.")
