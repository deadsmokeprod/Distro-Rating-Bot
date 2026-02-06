from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BACK_BUTTON_TEXT = "⬅️ Назад"


def make_keyboard(labels: list[str]) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=label)] for label in labels]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
