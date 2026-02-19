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
SELLER_MENU_DISPUTES = "⚖️ Споры"
SELLER_MENU_DISPUTE = "⚖️ Оспорить продажи"
SELLER_MENU_DISPUTE_MODERATE = "⚖️ Спорные продажи"
SELLER_MENU_COMPANY_RATING = "🏢 Рейтинг"
SELLER_MENU_STAFF_COMPANIES = "🏢 Сотрудники и компании"
SELLER_MENU_RULES = SELLER_RULES
SELLER_MENU_MY_STAFF = "👥 Мои сотрудники"
SELLER_MENU_FIRE_STAFF = "🧯 Уволить сотрудника"
SELLER_FIRE_ACTIVE = "Уволить действующего"
SELLER_FIRE_FIRED = "Уволенные сотрудники"
SELLER_MENU_HELP = "ℹ️ Помощь"
SELLER_MENU_SCROLLS = "📜 Скрижали и помощь"
SELLER_SCROLLS_HELP = "📜 Наставления легиона"
SELLER_SCROLLS_SALES_HELP = "📈 Помощь в продажах"
SELLER_SCROLLS_APP_HELP = "🧩 Помощь с приложением"


def seller_start_menu():
    return build_reply_keyboard([SELLER_START_REGISTER, SELLER_SUPPORT])


def seller_main_menu(role: str = "seller"):
    labels = [
        SELLER_MENU_PROFILE,
        SELLER_MENU_SALES,
        SELLER_MENU_DISPUTES,
        SELLER_MENU_COMPANY_RATING,
        SELLER_MENU_SCROLLS,
    ]
    if role == "rop":
        labels.extend(
            [
                SELLER_MENU_STAFF_COMPANIES,
            ]
        )
    return build_reply_keyboard(labels)


def seller_back_menu():
    return build_reply_keyboard([BACK_TEXT])


def seller_profile_menu():
    return build_reply_keyboard([SELLER_MENU_REQUISITES, SELLER_MENU_FINANCE, SELLER_MENU_GOALS, BACK_TEXT])


def seller_retry_menu():
    return build_reply_keyboard([SELLER_START_REGISTER, SELLER_SUPPORT, BACK_TEXT])


def seller_support_menu():
    return build_reply_keyboard([SELLER_SUPPORT, BACK_TEXT])


def seller_role_menu():
    return build_reply_keyboard([SELLER_ROLE_SELLER, SELLER_ROLE_ROP, BACK_TEXT])


def seller_scrolls_menu():
    return build_reply_keyboard(
        [
            SELLER_SCROLLS_HELP,
            SELLER_SCROLLS_SALES_HELP,
            SELLER_SCROLLS_APP_HELP,
            SELLER_MENU_RULES,
            BACK_TEXT,
        ]
    )


def seller_disputes_menu(role: str = "seller"):
    labels = [
        SELLER_MENU_DISPUTE,
    ]
    if role == "rop":
        labels.append(SELLER_MENU_DISPUTE_MODERATE)
    labels.append(BACK_TEXT)
    return build_reply_keyboard(labels)


def seller_staff_companies_menu(role: str = "seller"):
    labels: list[str] = []
    if role == "rop":
        labels.extend([SELLER_MENU_MY_STAFF, SELLER_MENU_FIRE_STAFF])
    labels.append(BACK_TEXT)
    return build_reply_keyboard(labels)
