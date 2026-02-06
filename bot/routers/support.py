from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.config import BUTTONS, Config
from bot.db.repo import (
    add_support_message,
    close_ticket,
    create_support_ticket,
    get_open_ticket_by_user,
    get_ticket_by_thread,
)

router = Router()

CLOSE_BUTTON = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✅ Обращение выполнено")]],
    resize_keyboard=True,
)


class SupportState(StatesGroup):
    subject = State()
    description = State()


@router.message(F.text == BUTTONS["SUPPORT"], flags={"allow_support_bypass": True})
async def support_start(message: Message, state: FSMContext, session_factory, user):
    async with session_factory() as session:
        existing = await get_open_ticket_by_user(session, user.id)
    if existing:
        await message.answer("У вас уже есть активное обращение.", reply_markup=CLOSE_BUTTON)
        return
    await message.answer("Введите краткую тему обращения:")
    await state.set_state(SupportState.subject)


@router.message(SupportState.subject, flags={"allow_support_bypass": True})
async def support_subject(message: Message, state: FSMContext):
    await state.update_data(subject=(message.text or "").strip())
    await message.answer("Опишите проблему подробно:")
    await state.set_state(SupportState.description)


@router.message(SupportState.description, flags={"allow_support_bypass": True})
async def support_description(
    message: Message, state: FSMContext, config: Config, session_factory, user
):
    data = await state.get_data()
    subject = data.get("subject")
    description = message.text or ""
    topic = await message.bot.create_forum_topic(config.bot_support_group_id, subject)
    thread_id = topic.message_thread_id
    async with session_factory() as session:
        ticket = await create_support_ticket(
            session,
            user_id=user.id,
            org_id=user.org_id,
            curator_admin_tg_id=user.organization.created_by_admin_tg_id if user.organization else None,
            subject=subject,
            thread_id=thread_id,
        )
        await add_support_message(
            session, ticket.id, "user", "text", description, None
        )
    await message.bot.send_message(
        config.bot_support_group_id,
        (
            f"Обращение #{ticket.id}\n"
            f"Пользователь: @{message.from_user.username or ''} {message.from_user.full_name} ({message.from_user.id})\n"
            f"ФИО: {user.full_name}, роль: {user.role}\n"
            f"Организация: {user.organization.inn if user.organization else ''} "
            f"{user.organization.name if user.organization else ''}\n"
            f"Admin tg_id: {user.organization.created_by_admin_tg_id if user.organization else ''}\n\n"
            f"Описание: {description}"
        ),
        message_thread_id=thread_id,
    )
    await message.answer("Обращение создано. Ожидайте ответа.", reply_markup=CLOSE_BUTTON)
    await state.clear()


@router.message(F.text == "✅ Обращение выполнено", flags={"allow_support_bypass": True})
async def support_close(message: Message, config: Config, session_factory, user):
    async with session_factory() as session:
        ticket = await get_open_ticket_by_user(session, user.id)
        if not ticket:
            await message.answer("У вас нет активного обращения.")
            return
        await close_ticket(session, ticket.id, "user")
    try:
        await message.bot.delete_forum_topic(config.bot_support_group_id, ticket.thread_id)
    except TelegramBadRequest:
        pass
    await message.answer("Спасибо! Обращение закрыто.")


@router.message(F.chat.type == "private", flags={"allow_support_bypass": True})
async def forward_user_messages(message: Message, config: Config, session_factory, user):
    if message.chat.id != message.from_user.id:
        return
    async with session_factory() as session:
        ticket = await get_open_ticket_by_user(session, user.id)
        if not ticket:
            return
        try:
            await message.copy_to(
                config.bot_support_group_id, message_thread_id=ticket.thread_id
            )
        except TelegramBadRequest:
            await close_ticket(session, ticket.id, "auto")
            await message.answer("Обращение закрыто администратором.")
            return
        await add_support_message(
            session,
            ticket.id,
            "user",
            message.content_type,
            message.text or message.caption,
            _extract_file_id(message),
        )


@router.message(F.chat.id == F.chat.id, flags={"allow_unauthorized": True})
async def forward_support_messages(message: Message, config: Config, session_factory):
    if message.chat.id != config.bot_support_group_id or not message.is_topic_message:
        return
    async with session_factory() as session:
        ticket = await get_ticket_by_thread(session, message.message_thread_id)
        if not ticket:
            return
        await message.copy_to(ticket.user_id)
        await add_support_message(
            session,
            ticket.id,
            "support",
            message.content_type,
            message.text or message.caption,
            _extract_file_id(message),
        )


@router.message(F.forum_topic_closed, flags={"allow_unauthorized": True})
async def forum_topic_closed(message: Message, session_factory):
    if not message.is_topic_message:
        return
    async with session_factory() as session:
        ticket = await get_ticket_by_thread(session, message.message_thread_id)
        if not ticket:
            return
        await close_ticket(session, ticket.id, "admin")
    await message.bot.send_message(ticket.user_id, "Ваше обращение закрыто.")


def _extract_file_id(message: Message):
    if message.photo:
        return message.photo[-1].file_id
    if message.video:
        return message.video.file_id
    if message.document:
        return message.document.file_id
    if message.voice:
        return message.voice.file_id
    if message.audio:
        return message.audio.file_id
    return None
