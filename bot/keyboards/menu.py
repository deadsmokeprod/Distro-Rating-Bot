from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


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



def build_menu(button_codes: list[str]) -> ReplyKeyboardMarkup:
    buttons = [KeyboardButton(text=BUTTON_LABELS[code]) for code in button_codes if code in BUTTON_LABELS]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
