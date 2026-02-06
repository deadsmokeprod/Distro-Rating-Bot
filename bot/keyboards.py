from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.constants import (
    BACK_BUTTON_TEXT,
    CONFIRM_BY_NUMBER,
    CONFIRM_SHOW_UNCONFIRMED,
    MENU_CONFIRM_SALE,
    MENU_PROFILE,
    MENU_SETTINGS,
    MENU_SUPPORT,
    MENU_WORLD_RATING,
    ORG_ADD,
    ORG_LIST,
    PROFILE_EDIT_NAME,
    SETTINGS_ORGS,
    SETTINGS_SYNC_NOW,
    SUPPORT_CLOSE,
    SUPPORT_CREATE,
)


def _column_keyboard(labels: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)] for label in labels],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def main_menu(is_super_admin: bool) -> ReplyKeyboardMarkup:
    labels = [MENU_WORLD_RATING, MENU_CONFIRM_SALE, MENU_PROFILE, MENU_SUPPORT]
    if is_super_admin:
        labels.append(MENU_SETTINGS)
    return _column_keyboard(labels)


def profile_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([PROFILE_EDIT_NAME, BACK_BUTTON_TEXT])


def confirm_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([CONFIRM_SHOW_UNCONFIRMED, CONFIRM_BY_NUMBER, BACK_BUTTON_TEXT])


def support_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([SUPPORT_CREATE, SUPPORT_CLOSE, BACK_BUTTON_TEXT])


def settings_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([SETTINGS_SYNC_NOW, SETTINGS_ORGS, BACK_BUTTON_TEXT])


def organizations_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([ORG_ADD, ORG_LIST, BACK_BUTTON_TEXT])


def back_menu() -> ReplyKeyboardMarkup:
    return _column_keyboard([BACK_BUTTON_TEXT])
