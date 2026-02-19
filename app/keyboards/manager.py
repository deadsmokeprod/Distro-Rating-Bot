from __future__ import annotations

from app.keyboards.common import BACK_TEXT, build_reply_keyboard

MANAGER_MENU_REGISTER_ORG = "➕ Зарегистрировать организацию"
MANAGER_MENU_ORGS = "📋 Мои организации"
MANAGER_MENU_SYNC = "🔄 Обновить базу"
MANAGER_MENU_EXPORT_RATINGS = "📤 Выгрузить рейтинги в EXCEL"
MANAGER_MENU_BROADCAST = "📣 Рассылка продавцам"
MANAGER_MENU_CHANGE_INN = "🔁 Смена ИНН"
MANAGER_MENU_MERGE_ORGS = "🔗 Слияние компаний"
MANAGER_MENU_GOALS_ADMIN = "🎯 Личные цели (админ)"
MANAGER_MENU_RULES = "📎 Правила и рекомендации"
MANAGER_MENU_HELP = "ℹ️ Помощь"

ORG_CREATE_CONFIRM = "✅ Создать"
ORG_CREATE_OPEN_CARD = "📄 Открыть карточку"
ORG_CREATE_OPEN_CARD_FULL = "📄 Открыть карточку организации"
ORG_CREATE_BACK_TO_MENU = "⬅️ В главное меню"

ORG_RESET_CONFIRM = "✅ Сбросить"

ORG_ACTION_STAFF = "👥 Сотрудники"
ORG_ACTION_RESET_SELLER_PASSWORD = "🔄 Сбросить пароль SELLER"
ORG_ACTION_RESET_ROP_PASSWORD = "🔄 Сбросить пароль ROP"
MANAGER_MENU_FIRE_ROP = "🧯 Уволить РОП"


def manager_main_menu(is_admin_view: bool = False):
    labels = [
        MANAGER_MENU_REGISTER_ORG,
        MANAGER_MENU_ORGS,
        MANAGER_MENU_SYNC,
        MANAGER_MENU_EXPORT_RATINGS,
        MANAGER_MENU_BROADCAST,
        MANAGER_MENU_CHANGE_INN,
        MANAGER_MENU_RULES,
        MANAGER_MENU_FIRE_ROP,
        MANAGER_MENU_HELP,
    ]
    if is_admin_view:
        labels.extend(
            [
                MANAGER_MENU_MERGE_ORGS,
                MANAGER_MENU_GOALS_ADMIN,
            ]
        )
    return build_reply_keyboard(labels)


MANAGER_BROADCAST_ALL = "Всем продавцам"
MANAGER_BROADCAST_MY_ORGS = "Продавцам моих компаний"
MANAGER_BROADCAST_BY_ORG = "По выбранной компании"
MANAGER_BROADCAST_CONFIRM = "Отправить"


def manager_broadcast_target_menu(is_admin_view: bool = False):
    labels = [
        MANAGER_BROADCAST_MY_ORGS,
        MANAGER_BROADCAST_BY_ORG,
    ]
    if is_admin_view:
        labels.insert(0, MANAGER_BROADCAST_ALL)
    labels.append(BACK_TEXT)
    return build_reply_keyboard(labels)


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


GOALS_MENU_SUPERTASKS = "📌 Сверхзадачи"
GOALS_MENU_AVG_LEVELS = "📈 Уровни среднемесячного"
GOALS_MENU_DOWNLOAD_TEMPLATE = "📥 Скачать шаблон Excel"
GOALS_MENU_UPLOAD_TEMPLATE = "📤 Загрузить Excel"
GOALS_MENU_AVG_CREATE = "➕ Назначить уровень"


def manager_goals_menu():
    return build_reply_keyboard(
        [
            GOALS_MENU_SUPERTASKS,
            GOALS_MENU_AVG_LEVELS,
            BACK_TEXT,
        ]
    )


def manager_supertasks_menu():
    return build_reply_keyboard(
        [
            GOALS_MENU_DOWNLOAD_TEMPLATE,
            GOALS_MENU_UPLOAD_TEMPLATE,
            BACK_TEXT,
        ]
    )


def manager_avg_levels_menu():
    return build_reply_keyboard(
        [
            GOALS_MENU_AVG_CREATE,
            BACK_TEXT,
        ]
    )
