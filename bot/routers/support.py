from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramBadRequest

from bot.config import load_config
from bot.db.repo import (
    add_support_message,
    close_support_ticket,
    create_support_ticket,
    get_org_by_id,
    get_support_ticket_by_thread,
    get_support_ticket_by_user,
    get_user_by_id,
)
from bot.keyboards.menu import close_support_keyboard


router = Router()


class SupportStates(StatesGroup):
    subject = State()
    description = State()
    in_ticket = State()


@router.message(lambda message: message.text == "Создать обращение в техподдержку")
async def support_start(message: Message, state: FSMContext, session: AsyncSession, user):
    existing = await get_support_ticket_by_user(session, user.id)
    if existing:
        await message.answer("У вас уже есть открытое обращение.")
        return
    await message.answer("Введите краткую тему обращения:")
    await state.set_state(SupportStates.subject)


@router.message(SupportStates.subject)
async def support_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text.strip())
    await message.answer("Введите полное описание:")
    await state.set_state(SupportStates.description)


@router.message(SupportStates.description)
async def support_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user,
    bot: Bot,
):
    data = await state.get_data()
    config = load_config()
    subject = data["subject"]
    topic = await bot.create_forum_topic(config.bot_support_group_id, name=subject)
    org = await get_org_by_id(session, user.org_id) if user.org_id else None
    curator_tg_id = org.created_by_admin_tg_id if org else None
    ticket = await create_support_ticket(
        session,
        user_id=user.id,
        org_id=org.id if org else None,
        curator_admin_tg_id=curator_tg_id,
        subject=subject,
        thread_id=topic.message_thread_id,
    )
    admin_line = f"Admin tg_id: {curator_tg_id}" if curator_tg_id else "Admin tg_id: -"
    if curator_tg_id:
        admin_line = f"Admin: <a href=\"tg://user?id={curator_tg_id}\">{curator_tg_id}</a>"
    username = message.from_user.username or "без_username"
    initial_message = (
        f"Номер обращения: {ticket.id}\n"
        f"Пользователь: @{username} ({message.from_user.full_name}), tg_id: {message.from_user.id}\n"
        f"ФИО: {user.full_name}, роль: {user.role}\n"
        f"Организация: {org.inn if org else '-'} {org.name if org else '-'}\n"
        f"{admin_line}"
    )
    await bot.send_message(
        config.bot_support_group_id,
        initial_message,
        message_thread_id=topic.message_thread_id,
    )
    await bot.send_message(
        config.bot_support_group_id,
        message.text,
        message_thread_id=topic.message_thread_id,
    )
    await add_support_message(session, ticket.id, "user", "text", message.text, None)
    await message.answer(
        "Обращение создано. Ожидайте ответа поддержки.",
        reply_markup=close_support_keyboard(),
    )
    await state.set_state(SupportStates.in_ticket)


@router.message(SupportStates.in_ticket)
async def forward_user_message(
    message: Message,
    session: AsyncSession,
    user,
    bot: Bot,
):
    ticket = await get_support_ticket_by_user(session, user.id)
    if not ticket:
        await message.answer("Обращение закрыто.")
        return
    config = load_config()
    try:
        await bot.copy_message(
            chat_id=config.bot_support_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=ticket.thread_id,
        )
    except TelegramBadRequest:
        await close_support_ticket(session, ticket.id, "auto")
        await message.answer("Обращение закрыто администратором.")
        return
    msg_type = "text"
    file_id = None
    text = message.text or message.caption
    if message.photo:
        msg_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        msg_type = "video"
        file_id = message.video.file_id
    elif message.document:
        msg_type = "document"
        file_id = message.document.file_id
    elif message.voice:
        msg_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        msg_type = "audio"
        file_id = message.audio.file_id
    await add_support_message(session, ticket.id, "user", msg_type, text, file_id)


@router.message(F.chat.type == "private")
async def forward_user_message_no_state(message: Message, session: AsyncSession, user, bot: Bot):
    ticket = await get_support_ticket_by_user(session, user.id)
    if not ticket or ticket.status != "OPEN":
        return
    config = load_config()
    try:
        await bot.copy_message(
            chat_id=config.bot_support_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=ticket.thread_id,
        )
    except TelegramBadRequest:
        await close_support_ticket(session, ticket.id, "auto")
        await message.answer("Обращение закрыто администратором.")
        return
    msg_type = "text"
    file_id = None
    text = message.text or message.caption
    if message.photo:
        msg_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        msg_type = "video"
        file_id = message.video.file_id
    elif message.document:
        msg_type = "document"
        file_id = message.document.file_id
    elif message.voice:
        msg_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        msg_type = "audio"
        file_id = message.audio.file_id
    await add_support_message(session, ticket.id, "user", msg_type, text, file_id)


@router.message(lambda message: message.text == "✅ Обращение выполнено")
async def close_ticket(message: Message, session: AsyncSession, user, bot: Bot, state: FSMContext):
    ticket = await get_support_ticket_by_user(session, user.id)
    if not ticket:
        await message.answer("Нет активного обращения.")
        return
    config = load_config()
    try:
        await bot.delete_forum_topic(config.bot_support_group_id, ticket.thread_id)
    except TelegramBadRequest:
        pass
    await close_support_ticket(session, ticket.id, "user")
    await message.answer("Спасибо, обращение закрыто.")
    await state.clear()


@router.message()
async def forward_support_message(message: Message, session: AsyncSession, bot: Bot):
    config = load_config()
    if message.chat.id != config.bot_support_group_id:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if not message.message_thread_id:
        return
    ticket = await get_support_ticket_by_thread(session, message.message_thread_id)
    if not ticket or ticket.status != "OPEN":
        return
    user = await get_user_by_id(session, ticket.user_id)
    if not user:
        return
    await bot.copy_message(
        chat_id=user.tg_id, from_chat_id=message.chat.id, message_id=message.message_id
    )
    msg_type = "text"
    file_id = None
    text = message.text or message.caption
    if message.photo:
        msg_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        msg_type = "video"
        file_id = message.video.file_id
    elif message.document:
        msg_type = "document"
        file_id = message.document.file_id
    elif message.voice:
        msg_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        msg_type = "audio"
        file_id = message.audio.file_id
    await add_support_message(session, ticket.id, "support", msg_type, text, file_id)


@router.message(F.forum_topic_closed)
async def topic_closed(message: Message, session: AsyncSession, bot: Bot):
    if message.chat.id != load_config().bot_support_group_id:
        return
    thread_id = message.message_thread_id
    ticket = await get_support_ticket_by_thread(session, thread_id)
    if ticket:
        await close_support_ticket(session, ticket.id, "admin")
        user = await get_user_by_id(session, ticket.user_id)
        if user:
            await bot.send_message(user.tg_id, "Обращение закрыто администратором.")
