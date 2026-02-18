from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

SELLER_START_REGISTER = "📝 Регистрация в компании"
SELLER_SUPPORT = "🆘 Техподдержка"
SELLER_RULES = "📎 Правила и рекомендации"
SELLER_ROLE_SELLER = "Продавец"
SELLER_ROLE_ROP = "РОП"

SELLER_MENU_PROFILE = "👤 Профиль"
SELLER_MENU_REQUISITES = "📋 Реквизиты"
SELLER_MENU_SALES = "✅ Фиксация продажи"
SELLER_MENU_FINANCE = "💳 Финансы"
SELLER_MENU_GOALS = "🎯 Личные цели"
SELLER_MENU_DISPUTE = "⚖️ Оспорить продажу"
SELLER_MENU_DISPUTE_MODERATE = "⚖️ Спорные продажи"
SELLER_MENU_COMPANY_RATING = "🏢 Рейтинг в компании за месяц"
SELLER_MENU_RULES = SELLER_RULES
SELLER_MENU_MY_STAFF = "👥 Мои сотрудники"
SELLER_MENU_FIRE_STAFF = "🧯 Уволить сотрудника"
SELLER_FIRE_ACTIVE = "Уволить действующего"
SELLER_FIRE_FIRED = "Уволенные сотрудники"
SELLER_MENU_HELP = "ℹ️ Помощь"


def seller_start_menu():
    return build_reply_keyboard([SELLER_START_REGISTER, SELLER_SUPPORT, SELLER_RULES])


def seller_main_menu():
    return build_reply_keyboard(
        [
            SELLER_MENU_PROFILE,
            SELLER_MENU_SALES,
            SELLER_MENU_FINANCE,
            SELLER_MENU_GOALS,
            SELLER_MENU_DISPUTE,
            SELLER_MENU_DISPUTE_MODERATE,
            SELLER_MENU_COMPANY_RATING,
            SELLER_MENU_MY_STAFF,
            SELLER_MENU_FIRE_STAFF,
            SELLER_MENU_RULES,
            SELLER_MENU_HELP,
        ]
    )


def seller_back_menu():
    return build_reply_keyboard([BACK_TEXT])


def seller_profile_menu():
    return build_reply_keyboard([SELLER_MENU_REQUISITES, BACK_TEXT])


def seller_retry_menu():
    return build_reply_keyboard([SELLER_START_REGISTER, SELLER_SUPPORT, SELLER_RULES, BACK_TEXT])


def seller_support_menu():
    return build_reply_keyboard([SELLER_SUPPORT, SELLER_RULES, BACK_TEXT])


def seller_role_menu():
    return build_reply_keyboard([SELLER_ROLE_SELLER, SELLER_ROLE_ROP, BACK_TEXT])
