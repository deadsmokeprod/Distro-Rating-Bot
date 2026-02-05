from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.config import load_config
from bot.db.engine import get_sessionmaker
from bot.db.repo import (
    add_support_message,
    close_ticket,
    create_support_ticket,
    get_open_ticket_by_user,
    get_org_by_id,
    get_ticket_by_thread,
    get_user_by_id,
)
from bot.keyboards.menu import BUTTON_LABELS
from bot.services.audit import log_menu_click

router = Router()


class SupportState(StatesGroup):
    input_subject = State()
    input_description = State()


def _support_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Обращение выполнено")]],
        resize_keyboard=True,
    )


@router.message(lambda m: m.text == BUTTON_LABELS["SUPPORT"])
async def support_start(message: Message, state: FSMContext, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "SUPPORT")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ticket = await get_open_ticket_by_user(session, db_user.id)
    if ticket:
        await message.answer("У вас уже есть открытое обращение.", reply_markup=_support_keyboard())
        return
    await message.answer("Введите краткую тему обращения:")
    await state.set_state(SupportState.input_subject)


@router.message(SupportState.input_subject)
async def support_subject(message: Message, state: FSMContext) -> None:
    subject = (message.text or "").strip()
    if not subject:
        await message.answer("Тема обязательна. Введите краткую тему:")
        return
    await state.update_data(subject=subject)
    await message.answer("Опишите проблему подробно:")
    await state.set_state(SupportState.input_description)


@router.message(SupportState.input_description)
async def support_description(message: Message, state: FSMContext, db_user, bot) -> None:
    description = (message.text or "").strip()
    if not description:
        await message.answer("Описание обязательно. Введите описание:")
        return
    data = await state.get_data()
    subject = data.get("subject")
    config = load_config()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_id(session, db_user.org_id) if db_user.org_id else None
        topic = await bot.create_forum_topic(chat_id=config.support_group_id, name=subject)
        ticket = await create_support_ticket(
            session,
            user_id=db_user.id,
            org_id=db_user.org_id,
            curator_admin_tg_id=org.created_by_admin_tg_id if org else None,
            subject=subject,
            thread_id=topic.message_thread_id,
        )
    admin_info = (
        f"Admin tg_id: {org.created_by_admin_tg_id}"
        if org
        else "Admin tg_id: неизвестен"
    )
    header = (
        f"Обращение #{ticket.id}\n"
        f"Пользователь: @{message.from_user.username or ''} {message.from_user.full_name} ({message.from_user.id})\n"
        f"ФИО: {db_user.full_name}, роль: {db_user.role}\n"
        f"Организация: {org.inn if org else '-'} {org.name if org else '-'}\n"
        f"{admin_info}"
    )
    await bot.send_message(
        chat_id=config.support_group_id,
        message_thread_id=ticket.thread_id,
        text=f"{header}\n\n{description}",
    )
    async with sessionmaker() as session:
        await add_support_message(session, ticket.id, "user", "text", description, None)
    await message.answer("Обращение создано. Мы скоро ответим.", reply_markup=_support_keyboard())
    await state.clear()


@router.message(lambda m: m.text == "✅ Обращение выполнено")
async def support_close_by_user(message: Message, db_user, bot) -> None:
    config = load_config()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ticket = await get_open_ticket_by_user(session, db_user.id)
        if not ticket:
            await message.answer("У вас нет открытых обращений.")
            return
        await close_ticket(session, ticket.id, "user")
    try:
        await bot.delete_forum_topic(config.support_group_id, ticket.thread_id)
    except TelegramBadRequest:
        pass
    await message.answer("Спасибо! Обращение закрыто.")


@router.message(lambda m: m.chat.type == "private")
async def forward_user_messages(message: Message, db_user, bot) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ticket = await get_open_ticket_by_user(session, db_user.id)
    if not ticket:
        return
    config = load_config()
    try:
        await message.copy_to(
            chat_id=config.support_group_id,
            message_thread_id=ticket.thread_id,
        )
    except TelegramBadRequest:
        async with sessionmaker() as session:
            await close_ticket(session, ticket.id, "auto")
        await message.answer("Обращение закрыто администратором.")
        return
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    async with sessionmaker() as session:
        await add_support_message(
            session,
            ticket.id,
            "user",
            message.content_type,
            message.text or message.caption,
            file_id,
        )


@router.message(lambda m: m.chat.type != "private" and m.message_thread_id is not None)
async def forward_support_messages(message: Message, bot) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ticket = await get_ticket_by_thread(session, message.message_thread_id)
        if not ticket or ticket.status != "OPEN":
            return
        user = await get_user_by_id(session, ticket.user_id)
        if not user:
            return
    try:
        await message.copy_to(chat_id=user.tg_id)
    except TelegramBadRequest:
        async with sessionmaker() as session:
            await close_ticket(session, ticket.id, "auto")
        return
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    async with sessionmaker() as session:
        await add_support_message(
            session,
            ticket.id,
            "support",
            message.content_type,
            message.text or message.caption,
            file_id,
        )


@router.message(lambda m: m.forum_topic_closed is not None)
async def handle_topic_closed(message: Message) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ticket = await get_ticket_by_thread(session, message.message_thread_id)
        if ticket and ticket.status == "OPEN":
            await close_ticket(session, ticket.id, "admin")
