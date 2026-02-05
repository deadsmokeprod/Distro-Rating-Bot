from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.config import load_config

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

SETTINGS_BUTTONS = {
    "REGISTER_DISTRIBUTOR": "Регистрация дистрибьютера",
    "SUPPORT_STATS": "Статистика по обращениям",
    "PAYOUT_REQUISITES": "Указание реквизитов для выплат",
    "FORCE_SYNC": "Принудительно обновить данные из 1С",
}


def main_menu(role: str) -> ReplyKeyboardMarkup:
    config = load_config()
    buttons = config.menu_config.get(role, [])
    keyboard = [[KeyboardButton(text=BUTTON_LABELS[item])] for item in buttons]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def settings_menu(role: str) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=SETTINGS_BUTTONS["PAYOUT_REQUISITES"])],
    ]
    if role in {"ADMIN", "SUPER_ADMIN"}:
        buttons.insert(0, [KeyboardButton(text=SETTINGS_BUTTONS["REGISTER_DISTRIBUTOR"])])
        buttons.insert(1, [KeyboardButton(text=SETTINGS_BUTTONS["SUPPORT_STATS"])])
        buttons.insert(2, [KeyboardButton(text=SETTINGS_BUTTONS["FORCE_SYNC"])])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def registration_choice() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Дистрибьютер")],
            [KeyboardButton(text="Продавец")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def close_support_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Обращение выполнено")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
