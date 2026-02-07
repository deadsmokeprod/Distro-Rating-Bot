from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

SELLER_COMPANY_YES = "✅ Да"
SELLER_COMPANY_NO = "❌ Нет"
SELLER_RETRY = "🔁 Попробовать снова"
SELLER_SUPPORT = "🆘 Написать в поддержку"

SELLER_MENU_PROFILE = "👤 Профиль"
SELLER_MENU_SALES = "✅ Фиксация продажи"
SELLER_MENU_GLOBAL_RATING = "🌍 Мировой рейтинг месяца"
SELLER_MENU_COMPANY_RATING = "🏢 Рейтинг в компании за месяц"
SELLER_MENU_HELP = "ℹ️ Помощь"


def seller_start_menu():
    return build_reply_keyboard([SELLER_COMPANY_YES, SELLER_COMPANY_NO])


def seller_main_menu():
    return build_reply_keyboard(
        [
            SELLER_MENU_PROFILE,
            SELLER_MENU_SALES,
            SELLER_MENU_GLOBAL_RATING,
            SELLER_MENU_COMPANY_RATING,
            SELLER_MENU_HELP,
        ]
    )


def seller_back_menu():
    return build_reply_keyboard([BACK_TEXT])


def seller_retry_menu():
    return build_reply_keyboard([SELLER_RETRY, SELLER_SUPPORT, BACK_TEXT])


def seller_support_menu():
    return build_reply_keyboard([SELLER_SUPPORT, BACK_TEXT])
