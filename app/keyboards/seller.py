from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

SELLER_REGISTER = "✅ Зарегистрироваться"
SELLER_RETRY = "🔁 Попробовать снова"
SELLER_SUPPORT = "🆘 Написать в поддержку"

SELLER_MENU_PROFILE = "👤 Профиль"
SELLER_MENU_HELP = "ℹ️ Помощь"


def seller_start_menu():
    return build_reply_keyboard([SELLER_REGISTER])


def seller_main_menu():
    return build_reply_keyboard([SELLER_MENU_PROFILE, SELLER_MENU_HELP])


def seller_back_menu():
    return build_reply_keyboard([BACK_TEXT])


def seller_retry_menu():
    return build_reply_keyboard([SELLER_RETRY, SELLER_SUPPORT, BACK_TEXT])
