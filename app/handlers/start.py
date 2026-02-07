from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import get_config
from app.keyboards.common import SUPPORT_CALLBACK
from app.db import sqlite
from app.keyboards.manager import manager_main_menu
from app.keyboards.seller import seller_main_menu, seller_start_menu

logger = logging.getLogger(__name__)

router = Router()


def is_manager(user_id: int) -> bool:
    config = get_config()
    return user_id in config.manager_ids


async def show_manager_menu(message: Message) -> None:
    await message.answer("Вы вошли как Менеджер.", reply_markup=manager_main_menu())


async def show_seller_menu(message: Message) -> None:
    config = get_config()
    await sqlite.update_last_seen(config.db_path, message.from_user.id)
    await message.answer("Главное меню", reply_markup=seller_main_menu())


async def show_seller_start(message: Message) -> None:
    await message.answer(
        "Вы ещё не зарегистрированы.\n"
        "Ваша компания зарегистрирована?",
        reply_markup=seller_start_menu(),
    )


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    config = get_config()
    user_id = message.from_user.id
    try:
        if is_manager(user_id):
            await show_manager_menu(message)
            return

        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        if user:
            await sqlite.update_last_seen(config.db_path, user_id)
            await show_seller_menu(message)
            return

        await show_seller_start(message)
    except Exception:
        logger.exception("Failed to handle /start")
        await message.answer("Произошла ошибка, попробуйте позже.")


@router.callback_query(F.data == SUPPORT_CALLBACK)
async def support_request_callback(callback: CallbackQuery) -> None:
    """По нажатию «Написать в техподдержку» (когда SUPPORT_USERNAME не задан) — уведомить поддержку."""
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    config = get_config()
    u = callback.from_user
    name = (u.first_name or "") + (" " + (u.last_name or "")).strip()
    username_part = f", @{u.username}" if u.username else ""
    try:
        await callback.bot.send_message(
            config.support_user_id,
            f"Запрос от пользователя: {name}, ID: <code>{u.id}</code>{username_part}.\n"
            "Напишите ему в Telegram (поиск по ID или username).",
        )
        await callback.message.answer("Запрос отправлен. Техподдержка свяжется с вами.")
    except Exception:
        logger.exception("Failed to notify support")
        await callback.message.answer("Не удалось отправить запрос. Попробуйте позже.")
