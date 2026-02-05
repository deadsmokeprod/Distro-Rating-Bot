from __future__ import annotations

from typing import Dict, List

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BUTTON_LABELS = {
    "RATING_EXPORT": "Рейтинг выгрузка",
    "MY_DISTRIBUTORS": "Рейтинг моих дистрибьютеров",
    "RATING_PERSONAL": "Рейтинг в этом месяце — личный",
    "RATING_ORG": "Рейтинг в этом месяце — в компании дистрибьютера",
    "RATING_ALL": "Рейтинг в этом месяце — все компании",
    "CONFIRM_SALE": "Зафиксировать продажу",
    "PROFILE": "Профиль и данные",
    "SETTINGS": "Настройки (админская панель)",
    "SUPPORT": "Создать обращение в техподдержку",
}


def build_menu(menu_config: Dict[str, List[str]], role: str) -> ReplyKeyboardMarkup:
    buttons = menu_config.get(role, [])
    keyboard_rows = []
    row = []
    for key in buttons:
        label = BUTTON_LABELS.get(key, key)
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)
    return ReplyKeyboardMarkup(keyboard=keyboard_rows, resize_keyboard=True)
