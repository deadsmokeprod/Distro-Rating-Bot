from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from ..keyboards.menu import BUTTON_LABELS, build_menu
from ..db.repo import (
    get_support_ticket_by_user,
    create_support_ticket,
    close_support_ticket,
    add_support_message,
    get_support_ticket_by_thread,
    get_org_by_id,
    get_user_by_id,
)

router = Router()


class SupportState(StatesGroup):
    subject = State()
    description = State()


CLOSE_BUTTON = "✅ Обращение выполнено"


@router.message(F.text == BUTTON_LABELS["SUPPORT"], flags={"allow_support_actions": True})
async def support_start(message: Message, state: FSMContext, db_user, session):
    ticket = await get_support_ticket_by_user(session, db_user.id)
    if ticket:
        await message.answer("У вас уже есть активное обращение.")
        return
    await message.answer("Введите краткую тему обращения:")
    await state.set_state(SupportState.subject)


@router.message(SupportState.subject, flags={"allow_support_actions": True})
async def support_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text.strip())
    await message.answer("Введите полное описание обращения:")
    await state.set_state(SupportState.description)


@router.message(SupportState.description, flags={"allow_support_actions": True})
async def support_description(message: Message, state: FSMContext, db_user, session, bot, config):
    data = await state.get_data()
    subject = data.get("subject") or "Без темы"
    description = message.text
    org = await get_org_by_id(session, db_user.org_id) if db_user.org_id else None
    thread = await bot.create_forum_topic(chat_id=config.support_group_id, name=subject)
    ticket = await create_support_ticket(
        session,
        user_id=db_user.id,
        org_id=db_user.org_id,
        curator_admin_tg_id=org.created_by_admin_tg_id if org else None,
        subject=subject,
        thread_id=thread.message_thread_id,
    )
    admin_line = f"Admin tg_id: {org.created_by_admin_tg_id}" if org else "Admin tg_id: неизвестен"
    text = (
        f"Обращение #{ticket.id}\n"
        f"Пользователь: @{message.from_user.username or 'нет'} / {message.from_user.full_name} (tg_id {message.from_user.id})\n"
        f"ФИО: {db_user.full_name}, роль: {db_user.role}\n"
        f"Организация: {org.inn if org else '-'} {org.name if org else '-'}\n"
        f"{admin_line}\n\n"
        f"Описание: {description}"
    )
    await bot.send_message(chat_id=config.support_group_id, message_thread_id=thread.message_thread_id, text=text)
    await add_support_message(session, ticket.id, "user", "text", description, None)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CLOSE_BUTTON)]], resize_keyboard=True
    )
    await message.answer("Обращение создано. Ожидайте ответ.", reply_markup=keyboard)
    await state.clear()


@router.message(F.text == CLOSE_BUTTON, flags={"allow_support_actions": True})
async def close_ticket(message: Message, db_user, session, bot, config):
    ticket = await get_support_ticket_by_user(session, db_user.id)
    if not ticket:
        await message.answer("Нет активного обращения.")
        return
    try:
        await bot.delete_forum_topic(chat_id=config.support_group_id, message_thread_id=ticket.thread_id)
    except TelegramBadRequest:
        pass
    await close_support_ticket(session, ticket.id, "user")
    buttons = config.menu_config.get(db_user.role, [])
    await message.answer("Спасибо!", reply_markup=build_menu(buttons))


@router.message(F.chat.type == ChatType.SUPERGROUP, flags={"allow_support_actions": True})
async def support_group_messages(message: Message, session, bot, config):
    if message.chat.id != config.support_group_id:
        return
    if not message.message_thread_id:
        return
    if message.forum_topic_closed:
        ticket = await get_support_ticket_by_thread(session, message.message_thread_id)
        if ticket and ticket.status == "OPEN":
            await close_support_ticket(session, ticket.id, "admin")
            user = await get_user_by_id(session, ticket.user_id) if ticket.user_id else None
            if user:
                await bot.send_message(chat_id=user.tg_id, text="Обращение закрыто администратором.")
        return
    ticket = await get_support_ticket_by_thread(session, message.message_thread_id)
    if not ticket or ticket.status != "OPEN":
        return
    user = await get_user_by_id(session, ticket.user_id) if ticket.user_id else None
    if not user:
        return
    if message.text:
        await bot.send_message(chat_id=user.tg_id, text=message.text)
        await add_support_message(session, ticket.id, "support", "text", message.text, None)
    elif message.photo:
        file_id = message.photo[-1].file_id
        await bot.send_photo(chat_id=user.tg_id, photo=file_id, caption=message.caption)
        await add_support_message(session, ticket.id, "support", "photo", message.caption, file_id)
    elif message.document:
        file_id = message.document.file_id
        await bot.send_document(chat_id=user.tg_id, document=file_id, caption=message.caption)
        await add_support_message(session, ticket.id, "support", "document", message.caption, file_id)
    elif message.voice:
        file_id = message.voice.file_id
        await bot.send_voice(chat_id=user.tg_id, voice=file_id, caption=message.caption)
        await add_support_message(session, ticket.id, "support", "voice", message.caption, file_id)
    elif message.audio:
        file_id = message.audio.file_id
        await bot.send_audio(chat_id=user.tg_id, audio=file_id, caption=message.caption)
        await add_support_message(session, ticket.id, "support", "audio", message.caption, file_id)
    elif message.video:
        file_id = message.video.file_id
        await bot.send_video(chat_id=user.tg_id, video=file_id, caption=message.caption)
        await add_support_message(session, ticket.id, "support", "video", message.caption, file_id)


@router.message(flags={"allow_support_actions": True})
async def forward_user_messages(message: Message, db_user, session, bot, config):
    if not db_user:
        return
    ticket = await get_support_ticket_by_user(session, db_user.id)
    if not ticket:
        return
    try:
        if message.text:
            await bot.send_message(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                text=message.text,
            )
            await add_support_message(session, ticket.id, "user", "text", message.text, None)
        elif message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                photo=file_id,
                caption=message.caption,
            )
            await add_support_message(session, ticket.id, "user", "photo", message.caption, file_id)
        elif message.document:
            file_id = message.document.file_id
            await bot.send_document(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                document=file_id,
                caption=message.caption,
            )
            await add_support_message(session, ticket.id, "user", "document", message.caption, file_id)
        elif message.voice:
            file_id = message.voice.file_id
            await bot.send_voice(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                voice=file_id,
                caption=message.caption,
            )
            await add_support_message(session, ticket.id, "user", "voice", message.caption, file_id)
        elif message.audio:
            file_id = message.audio.file_id
            await bot.send_audio(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                audio=file_id,
                caption=message.caption,
            )
            await add_support_message(session, ticket.id, "user", "audio", message.caption, file_id)
        elif message.video:
            file_id = message.video.file_id
            await bot.send_video(
                chat_id=config.support_group_id,
                message_thread_id=ticket.thread_id,
                video=file_id,
                caption=message.caption,
            )
            await add_support_message(session, ticket.id, "user", "video", message.caption, file_id)
    except TelegramBadRequest:
        await close_support_ticket(session, ticket.id, "auto")
        await message.answer("Обращение закрыто (тема была удалена).")
