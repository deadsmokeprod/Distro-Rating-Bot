from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

from aiogram.types import Message, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_active_reply_menus: Dict[Tuple[int, int], int] = {}


def _menu_key(chat_id: int, actor_tg_user_id: int) -> tuple[int, int]:
    return (chat_id, actor_tg_user_id)


async def clear_active_reply_menu(message: Message, actor_tg_user_id: int) -> None:
    chat_id = int(message.chat.id)
    key = _menu_key(chat_id, actor_tg_user_id)
    async with _lock:
        prev_message_id = _active_reply_menus.get(key)
    if not prev_message_id:
        return
    try:
        await message.bot.delete_message(chat_id=chat_id, message_id=prev_message_id)
    except Exception:
        logger.debug("Failed to clear previous reply menu message_id=%s", prev_message_id)
    finally:
        async with _lock:
            if _active_reply_menus.get(key) == prev_message_id:
                _active_reply_menus.pop(key, None)


async def send_single_reply_menu(
    message: Message,
    actor_tg_user_id: int,
    text: str,
    reply_markup: ReplyKeyboardMarkup,
) -> Message:
    await clear_active_reply_menu(message, actor_tg_user_id)
    sent = await message.answer(text, reply_markup=reply_markup)
    key = _menu_key(int(sent.chat.id), actor_tg_user_id)
    async with _lock:
        _active_reply_menus[key] = int(sent.message_id)
    return sent
