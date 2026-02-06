from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

MANAGER_MENU_REGISTER_ORG = "➕ Зарегистрировать организацию"
MANAGER_MENU_ORGS = "📋 Мои организации"
MANAGER_MENU_HELP = "ℹ️ Помощь"

ORG_CREATE_CONFIRM = "✅ Создать"
ORG_CREATE_OPEN_CARD = "📄 Открыть карточку"
ORG_CREATE_OPEN_CARD_FULL = "📄 Открыть карточку организации"
ORG_CREATE_BACK_TO_MENU = "⬅️ В главное меню"

ORG_RESET_CONFIRM = "✅ Сбросить"

ORG_ACTION_STAFF = "👥 Сотрудники"
ORG_ACTION_RESET_PASSWORD = "🔄 Сбросить пароль организации"


def manager_main_menu():
    return build_reply_keyboard(
        [MANAGER_MENU_REGISTER_ORG, MANAGER_MENU_ORGS, MANAGER_MENU_HELP]
    )


def manager_back_menu():
    return build_reply_keyboard([BACK_TEXT])


def org_create_confirm_menu():
    return build_reply_keyboard([ORG_CREATE_CONFIRM, BACK_TEXT])


def org_created_menu():
    return build_reply_keyboard([ORG_CREATE_OPEN_CARD_FULL, ORG_CREATE_BACK_TO_MENU])


def org_exists_menu():
    return build_reply_keyboard([ORG_CREATE_OPEN_CARD, BACK_TEXT])


def org_reset_confirm_menu():
    return build_reply_keyboard([ORG_RESET_CONFIRM, BACK_TEXT])
