from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_active_menus: Dict[Tuple[int, int], int] = {}


def _menu_key(chat_id: int, actor_tg_user_id: int) -> tuple[int, int]:
    return (chat_id, actor_tg_user_id)


async def clear_active_inline_menu(message: Message, actor_tg_user_id: int) -> None:
    """Delete previously tracked inline menu for user in chat."""
    chat_id = int(message.chat.id)
    key = _menu_key(chat_id, actor_tg_user_id)
    async with _lock:
        prev_message_id = _active_menus.get(key)
    if not prev_message_id:
        return
    try:
        await message.bot.delete_message(chat_id=chat_id, message_id=prev_message_id)
    except Exception:
        # If message cannot be deleted, best effort: try to disable old buttons.
        try:
            await message.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=prev_message_id,
                reply_markup=None,
            )
        except Exception:
            logger.debug("Failed to clear previous inline menu message_id=%s", prev_message_id)
    finally:
        async with _lock:
            if _active_menus.get(key) == prev_message_id:
                _active_menus.pop(key, None)


async def send_single_inline_menu(
    message: Message,
    actor_tg_user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> Message:
    """Send inline menu and keep only one active per user in chat."""
    await clear_active_inline_menu(message, actor_tg_user_id)
    sent = await message.answer(text, reply_markup=reply_markup)
    key = _menu_key(int(sent.chat.id), actor_tg_user_id)
    async with _lock:
        _active_menus[key] = int(sent.message_id)
    return sent


async def mark_inline_menu_active(message: Message, actor_tg_user_id: int) -> None:
    """Track edited/current message as active inline menu."""
    key = _menu_key(int(message.chat.id), actor_tg_user_id)
    async with _lock:
        _active_menus[key] = int(message.message_id)


async def get_active_inline_menu_message_id(
    chat_id: int, actor_tg_user_id: int
) -> int | None:
    key = _menu_key(chat_id, actor_tg_user_id)
    async with _lock:
        value = _active_menus.get(key)
    return int(value) if value is not None else None

