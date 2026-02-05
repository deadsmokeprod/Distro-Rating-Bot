from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.config import BUTTONS


def build_menu(button_ids):
    rows = []
    current = []
    for button_id in button_ids:
        label = BUTTONS.get(button_id, button_id)
        current.append(KeyboardButton(text=label))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
