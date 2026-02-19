from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

BACK_TEXT = "⬅️ Назад"


def build_reply_keyboard(labels: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)] for label in labels],
        resize_keyboard=True,
    )


def build_inline_keyboard(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)] for text, data in buttons]
    )


SUPPORT_CALLBACK = "support_request"
MANAGER_HELP_CALLBACK = "manager_help_request"


def support_contact_line(support_username: str | None) -> str:
    if support_username:
        return f"\n\nНаписать в техподдержку: https://t.me/{support_username}"
    return ""


def support_inline_keyboard(
    support_user_id: int,
    support_username: str | None = None,
) -> InlineKeyboardMarkup:
    if support_username:
        url = f"https://t.me/{support_username}"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Оставить обращение", callback_data=SUPPORT_CALLBACK)],
                [InlineKeyboardButton(text="👉 Написать в Telegram", url=url)],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Оставить обращение", callback_data=SUPPORT_CALLBACK)]
        ]
    )


def support_confirm_keyboard(token: str, can_send: bool = True) -> InlineKeyboardMarkup:
    send_button = ("✅ Отправить", f"support_send:{token}")
    return build_inline_keyboard(
        [
            send_button,
            ("❌ Отмена", f"support_cancel:{token}"),
        ]
    )


def manager_help_inline_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard([("🤝 Менеджер Медоварни", MANAGER_HELP_CALLBACK)])


def manager_help_confirm_keyboard(token: str, can_send: bool = True) -> InlineKeyboardMarkup:
    send_button = ("✅ Отправить", f"mhelp_send:{token}")
    return build_inline_keyboard(
        [
            send_button,
            ("❌ Отмена", f"mhelp_cancel:{token}"),
        ]
    )
