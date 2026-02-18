from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import get_config
from app.keyboards.common import SUPPORT_CALLBACK
from app.db import sqlite
from app.handlers.filters import PrivateChatFilter
from app.keyboards.manager import manager_main_menu
from app.keyboards.seller import seller_main_menu, seller_start_menu
from app.services.challenges import ensure_biweekly_challenges, get_current_challenge, update_challenge_progress
from app.services.leagues import compute_league
from app.services.ratings import current_month_rankings

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(PrivateChatFilter())
router.callback_query.filter(PrivateChatFilter())


def is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


def is_manager(user_id: int) -> bool:
    config = get_config()
    return user_id in config.manager_ids


def is_manager_or_admin(user_id: int) -> bool:
    return is_manager(user_id) or is_admin(user_id)


async def show_manager_menu(message: Message) -> None:
    role_name = "Администратор" if is_admin(message.from_user.id) else "Менеджер"
    await message.answer(f"Вы вошли как {role_name}.", reply_markup=manager_main_menu())


async def show_seller_menu(message: Message, tg_user_id: int | None = None) -> None:
    config = get_config()
    user_id = tg_user_id or message.from_user.id
    await sqlite.update_last_seen(config.db_path, user_id)
    await ensure_biweekly_challenges(config)
    challenge, _ = await update_challenge_progress(config, user_id)
    rows = await current_month_rankings(config.db_path)
    user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
    if user:
        org_id = int(user["org_id"])
        rows = [r for r in rows if r.org_id == org_id]
    league = compute_league(rows, user_id, rank_attr="company_rank")
    challenge_line = ""
    if challenge:
        challenge_line = (
            f"Челлендж: {challenge.progress_volume:g}/{challenge.target_volume:g} л\n"
        )
        if challenge.completed:
            challenge_line = "Челлендж выполнен ✅\n"
    league_line = f"Лига: {league.name}"
    if league.to_next_volume is not None:
        league_line += f", до повышения {league.to_next_volume:g} л"
    text = "Главное меню\n" + challenge_line + league_line
    await message.answer(text, reply_markup=seller_main_menu())


async def show_seller_start(message: Message) -> None:
    await message.answer(
        "Вы ещё не зарегистрированы.\n"
        "Выберите действие:",
        reply_markup=seller_start_menu(),
    )


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    config = get_config()
    user_id = message.from_user.id
    try:
        if is_manager_or_admin(user_id):
            await show_manager_menu(message)
            return

        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        if user:
            if str(user["status"]) == "fired":
                org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
                inn = org["inn"] if org else "-"
                name = org["name"] if org else "Неизвестная организация"
                await message.answer(
                    f"Вы уволены из компании {inn} {name}.\n"
                    "Для продолжения нажмите «📝 Регистрация в компании».",
                    reply_markup=seller_start_menu(),
                )
                return
            await sqlite.update_last_seen(config.db_path, user_id)
            await show_seller_menu(message, user_id)
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
