from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

MANAGER_MENU_REGISTER_ORG = "➕ Зарегистрировать организацию"
MANAGER_MENU_ORGS = "📋 Мои организации"
MANAGER_MENU_SYNC = "🔄 Обновить базу"
MANAGER_MENU_EXPORT_RATINGS = "📤 Выгрузить рейтинги в EXCEL"
MANAGER_MENU_BROADCAST = "📣 Рассылка продавцам"
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
        [
            MANAGER_MENU_REGISTER_ORG,
            MANAGER_MENU_ORGS,
            MANAGER_MENU_SYNC,
            MANAGER_MENU_EXPORT_RATINGS,
            MANAGER_MENU_BROADCAST,
            MANAGER_MENU_HELP,
        ]
    )


MANAGER_BROADCAST_ALL = "Всем продавцам"
MANAGER_BROADCAST_MY_ORGS = "Продавцам моих компаний"
MANAGER_BROADCAST_CONFIRM = "Отправить"


def manager_broadcast_target_menu():
    return build_reply_keyboard([MANAGER_BROADCAST_ALL, MANAGER_BROADCAST_MY_ORGS, BACK_TEXT])


def manager_broadcast_confirm_menu():
    return build_reply_keyboard([MANAGER_BROADCAST_CONFIRM, BACK_TEXT])


def manager_back_menu():
    return build_reply_keyboard([BACK_TEXT])


MANAGER_SYNC_CURRENT_MONTH = "📅 Текущий месяц"
MANAGER_SYNC_CUSTOM_RANGE = "🗓️ Период ДДММГГГГ по ДДММГГГГ"


def manager_sync_menu():
    return build_reply_keyboard([MANAGER_SYNC_CURRENT_MONTH, MANAGER_SYNC_CUSTOM_RANGE, BACK_TEXT])


def org_create_confirm_menu():
    return build_reply_keyboard([ORG_CREATE_CONFIRM, BACK_TEXT])


def org_created_menu():
    return build_reply_keyboard([ORG_CREATE_OPEN_CARD_FULL, ORG_CREATE_BACK_TO_MENU])


def org_exists_menu():
    return build_reply_keyboard([ORG_CREATE_OPEN_CARD, BACK_TEXT])


def org_reset_confirm_menu():
    return build_reply_keyboard([ORG_RESET_CONFIRM, BACK_TEXT])
