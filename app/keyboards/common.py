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
                [InlineKeyboardButton(text="👉 Написать в техподдержку", url=url)]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👉 Написать в техподдержку", callback_data=SUPPORT_CALLBACK)]
        ]
    )
