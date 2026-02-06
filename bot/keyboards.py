from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BACK_TEXT = "⬅️ Назад"


def _one_column(buttons: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)] for label in buttons],
        resize_keyboard=True,
    )


def main_menu(is_super_admin: bool) -> ReplyKeyboardMarkup:
    items = [
        "🌍 Мировой рейтинг",
        "✅ Подтвердить продажу",
        "👤 Профиль",
        "🆘 Поддержка",
    ]
    if is_super_admin:
        items.append("⚙️ Настройки")
    return _one_column(items)


def profile_menu() -> ReplyKeyboardMarkup:
    return _one_column(["✏️ Изменить имя", BACK_TEXT])


def confirm_menu() -> ReplyKeyboardMarkup:
    return _one_column(["📋 Показать неподтверждённые", "🔎 Подтвердить по номеру", BACK_TEXT])


def settings_menu() -> ReplyKeyboardMarkup:
    return _one_column(["🔄 Запустить синхронизацию сейчас", "🏢 Организации", BACK_TEXT])


def organizations_menu() -> ReplyKeyboardMarkup:
    return _one_column(["➕ Добавить организацию", "📄 Список организаций", BACK_TEXT])


def support_menu() -> ReplyKeyboardMarkup:
    return _one_column(["✉️ Создать обращение", "⛔ Закрыть обращение", BACK_TEXT])


def back_only() -> ReplyKeyboardMarkup:
    return _one_column([BACK_TEXT])
