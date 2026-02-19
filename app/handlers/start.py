from __future__ import annotations

import html
import logging
import secrets

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.config import get_config
from app.keyboards.common import (
    MANAGER_HELP_CALLBACK,
    SUPPORT_CALLBACK,
    manager_help_confirm_keyboard,
    support_confirm_keyboard,
)
from app.db import sqlite
from app.handlers.filters import PrivateChatFilter
from app.keyboards.manager import manager_main_menu
from app.keyboards.common import BACK_TEXT
from app.keyboards.seller import (
    SELLER_MENU_COMPANY_RATING,
    SELLER_MENU_DISPUTE,
    SELLER_MENU_DISPUTE_MODERATE,
    SELLER_MENU_DISPUTES,
    SELLER_MENU_FINANCE,
    SELLER_MENU_FIRE_STAFF,
    SELLER_MENU_GOALS,
    SELLER_MENU_MY_STAFF,
    SELLER_MENU_PROFILE,
    SELLER_MENU_REQUISITES,
    SELLER_MENU_RULES,
    SELLER_MENU_SALES,
    SELLER_MENU_SCROLLS,
    SELLER_MENU_STAFF_COMPANIES,
    SELLER_SCROLLS_APP_HELP,
    SELLER_SCROLLS_HELP,
    SELLER_SCROLLS_SALES_HELP,
    SELLER_START_REGISTER,
    seller_main_menu,
    seller_scrolls_menu,
    seller_start_menu,
)
from app.services.challenges import ensure_biweekly_challenges, get_current_challenge, update_challenge_progress
from app.services.leagues import compute_league
from app.services.ratings import current_month_rankings
from app.utils.inline_menu import clear_active_inline_menu
from app.utils.nav_history import clear_history
from app.utils.rate_limit import acquire_rate_limit, release_rate_limit
from app.utils.reply_menu import send_single_reply_menu

logger = logging.getLogger(__name__)
_SELLER_MENU_COMMANDS = {
    BACK_TEXT,
    SELLER_START_REGISTER,
    SELLER_MENU_PROFILE,
    SELLER_MENU_REQUISITES,
    SELLER_MENU_SALES,
    SELLER_MENU_FINANCE,
    SELLER_MENU_GOALS,
    SELLER_MENU_DISPUTES,
    SELLER_MENU_DISPUTE,
    SELLER_MENU_DISPUTE_MODERATE,
    SELLER_MENU_COMPANY_RATING,
    SELLER_MENU_STAFF_COMPANIES,
    SELLER_MENU_MY_STAFF,
    SELLER_MENU_FIRE_STAFF,
    SELLER_MENU_SCROLLS,
    SELLER_SCROLLS_HELP,
    SELLER_SCROLLS_SALES_HELP,
    SELLER_SCROLLS_APP_HELP,
    SELLER_MENU_RULES,
}

router = Router()
router.message.filter(PrivateChatFilter())
router.callback_query.filter(PrivateChatFilter())


class SupportRequestStates(StatesGroup):
    wait_text = State()
    confirm = State()


class ManagerHelpRequestStates(StatesGroup):
    wait_text = State()
    confirm = State()


def is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


def is_manager(user_id: int) -> bool:
    config = get_config()
    return user_id in config.manager_ids


def is_manager_or_admin(user_id: int) -> bool:
    return is_manager(user_id) or is_admin(user_id)


async def show_manager_menu(message: Message) -> None:
    await clear_active_inline_menu(message, message.from_user.id)
    is_admin_view = is_admin(message.from_user.id)
    role_name = "Администратор" if is_admin_view else "Менеджер"
    text = (
        f"Вы вошли как {role_name}.\n"
        "Разделы:\n"
        "• ➕ Зарегистрировать организацию - добавить новую компанию.\n"
        "• 📋 Мои организации - карточки, сотрудники и действия по компании.\n"
        "• 🔄 Обновить базу - синхронизация данных продаж.\n"
        "• 📤 Выгрузить рейтинги в EXCEL - отчет по рейтингу.\n"
        "• 📣 Рассылка продавцам - массовые сообщения.\n"
        "• 🔁 Смена ИНН - корректировка ИНН компании.\n"
        "• ℹ️ Помощь - канал поддержки."
    )
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=text,
        reply_markup=manager_main_menu(is_admin_view=is_admin_view),
    )


async def show_seller_menu(message: Message, tg_user_id: int | None = None) -> None:
    config = get_config()
    user_id = tg_user_id or message.from_user.id
    await clear_active_inline_menu(message, user_id)
    await clear_history(user_id)
    await sqlite.update_last_seen(config.db_path, user_id)
    await ensure_biweekly_challenges(config)
    challenge, _ = await update_challenge_progress(config, user_id)
    rows = await current_month_rankings(config.db_path)
    user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
    user_role = str(user["role"]) if user else "seller"
    if user:
        org_id = int(user["org_id"])
        rows = [r for r in rows if r.org_id == org_id]
    league = compute_league(rows, user_id, rank_attr="company_rank")
    challenge_line = ""
    if challenge:
        challenge_line = (
            f"Испытание месяца: {challenge.progress_volume:g}/{challenge.target_volume:g} л\n"
        )
        if challenge.completed:
            challenge_line = "Испытание месяца пройдено ✅\n"
    league_line = f"Лига: {league.name}"
    if league.to_next_volume is not None:
        league_line += f", до повышения {league.to_next_volume:g} л"
    menu_guide = (
        "Главное меню:\n"
        "• 👤 Профиль — личный статус, реквизиты, финансы и цели.\n"
        "• ✅ Фиксация продажи — закрепление новых продаж за собой.\n"
        "• ⚖️ Споры — оспаривание и отслеживание спорных продаж.\n"
        "• 🏢 Рейтинг — место в строю компании за месяц.\n"
        "• 📜 Скрижали — правила, помощь и полезные подсказки."
    )
    if user_role == "rop":
        menu_guide += "\n• 🏢 Сотрудники и компании — управление составом команды."
    text = (
        "🛡️ Легионер, добро пожаловать в главный лагерь.\n"
        "Держи темп: фиксируй продажи, укрепляй лигу и собирай медовую награду.\n\n"
        "Курс прозрачен: 1 🍯 МЕДкоин = 1 ₽.\n\n"
        + challenge_line
        + league_line
        + "\n\n"
        + menu_guide
    )
    await send_single_reply_menu(
        message,
        actor_tg_user_id=user_id,
        text=text,
        reply_markup=seller_main_menu(role=user_role),
    )


async def show_seller_start(message: Message) -> None:
    await clear_active_inline_menu(message, message.from_user.id)
    await clear_history(message.from_user.id)
    await send_single_reply_menu(
        message,
        actor_tg_user_id=message.from_user.id,
        text=(
            "Вы ещё не зарегистрированы.\n"
            "Выберите действие:\n"
            "• 📝 Регистрация в компании - создать профиль продавца/РОП.\n"
            "• 🆘 Техподдержка - отправить обращение."
        ),
        reply_markup=seller_start_menu(),
    )


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    config = get_config()
    user_id = message.from_user.id
    try:
        if is_manager_or_admin(user_id):
            await show_manager_menu(message)
            return

        user = await sqlite.get_user_by_tg_id(config.db_path, user_id)
        if user:
            if str(user["status"]) == "fired":
                org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
                inn = org["inn"] if org else "-"
                name = org["name"] if org else "Неизвестная организация"
                await message.answer(
                    f"Вы уволены из компании {inn} {name}.\n"
                    "Для продолжения нажмите «📝 Регистрация в компании».",
                    reply_markup=seller_start_menu(),
                )
                return
            await sqlite.update_last_seen(config.db_path, user_id)
            await show_seller_menu(message, user_id)
            return

        await show_seller_start(message)
    except Exception:
        logger.exception("Failed to handle /start")
        await message.answer("Произошла ошибка, попробуйте позже.")


def _extract_support_token(data: str | None, prefix: str) -> str | None:
    if not data or not data.startswith(prefix):
        return None
    _, token = data.split(":", 1)
    return token or None


async def _restore_seller_or_start_menu(message: Message, tg_user_id: int) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if user and str(user["status"]) == "active":
        await show_seller_menu(message, tg_user_id)
        return
    await show_seller_start(message)


async def _restore_seller_scrolls_or_start_menu(message: Message, tg_user_id: int) -> None:
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, tg_user_id)
    if user and str(user["status"]) == "active":
        await clear_active_inline_menu(message, tg_user_id)
        await send_single_reply_menu(
            message,
            actor_tg_user_id=tg_user_id,
            text=(
                "📜 Вы вернулись в раздел Скрижалей:\n"
                "• 📜 Наставления легиона - правила и рекомендации.\n"
                "• 📈 Помощь в продажах - обращение менеджеру Медоварни.\n"
                "• 🧩 Помощь с приложением - обращение в техподдержку."
            ),
            reply_markup=seller_scrolls_menu(),
        )
        return
    await show_seller_start(message)


def _support_preview_text(request_text: str) -> str:
    return (
        "Проверьте обращение перед отправкой:\n\n"
        f"{html.escape(request_text)}\n\n"
        "Нажмите «Отправить», если всё верно."
    )


def _manager_help_preview_text(request_text: str) -> str:
    return (
        "Проверьте обращение менеджеру перед отправкой:\n\n"
        f"{html.escape(request_text)}\n\n"
        "Нажмите «Отправить», если всё верно."
    )


def _request_content_type_label(message: Message) -> str:
    if message.photo:
        return "фото"
    if message.video:
        return "видео"
    if message.animation:
        return "анимация"
    if message.document:
        return "документ"
    if message.audio:
        return "аудио"
    if message.voice:
        return "голосовое сообщение"
    if message.video_note:
        return "видеосообщение"
    if message.sticker:
        return "стикер"
    if message.text:
        return "текст"
    return "сообщение"


def _extract_request_payload(message: Message) -> tuple[str | None, str]:
    raw_text = (message.text or "").strip()
    if raw_text:
        return "text", raw_text[:2000]
    has_media = any(
        [
            bool(message.photo),
            bool(message.video),
            bool(message.animation),
            bool(message.document),
            bool(message.audio),
            bool(message.voice),
            bool(message.video_note),
            bool(message.sticker),
        ]
    )
    if not has_media:
        return None, ""
    caption = (message.caption or "").strip()
    return _request_content_type_label(message), caption[:2000]


def _request_preview_text(title: str, content_kind: str, request_text: str) -> str:
    if content_kind == "text":
        body = html.escape(request_text)
    else:
        body = f"Тип вложения: {content_kind}"
        if request_text:
            body += f"\nКомментарий:\n{html.escape(request_text)}"
    return f"{title}\n\n{body}\n\nНажмите «Отправить», если всё верно."


@router.callback_query(F.data == MANAGER_HELP_CALLBACK)
async def manager_help_request_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, callback.from_user.id)
    if not user or str(user["status"]) != "active" or str(user["role"]) not in {"seller", "rop"}:
        await callback.answer(
            "Обращение к менеджеру доступно только зарегистрированным продавцам и РОП.",
            show_alert=True,
        )
        return
    org = await sqlite.get_org_by_id(config.db_path, int(user["org_id"]))
    manager_tg_user_id = int(org["created_by_manager_id"]) if org else 0
    if manager_tg_user_id <= 0:
        await callback.answer("Не удалось определить менеджера вашей компании.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(ManagerHelpRequestStates.wait_text)
    await state.set_data(
        {
            "manager_help_manager_tg_user_id": manager_tg_user_id,
            "manager_help_org_id": int(user["org_id"]),
            "manager_help_org_name": str(org["name"]) if org else "-",
            "manager_help_org_inn": str(org["inn"]) if org else "-",
        }
    )
    await callback.message.answer(
        "Подскажите, какая помощь нужна для усиления продаж! Вы можете отпраить видео, фото. "
        "Ваше обращение появится у Менеджера Медоварни.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ManagerHelpRequestStates.wait_text)
async def manager_help_collect_text(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    if raw_text and raw_text in _SELLER_MENU_COMMANDS:
        await state.clear()
        await message.answer("Текущее обращение менеджеру отменено.")
        await _restore_seller_scrolls_or_start_menu(message, message.from_user.id)
        return
    content_kind, request_text = _extract_request_payload(message)
    if content_kind is None:
        await message.answer(
            "Отправьте текст, фото, видео, файл или другое вложение одним сообщением."
        )
        return
    token = secrets.token_urlsafe(8)
    preview = await message.answer(
        _request_preview_text("Проверьте обращение менеджеру перед отправкой:", content_kind, request_text),
        reply_markup=manager_help_confirm_keyboard(token),
    )
    await state.set_state(ManagerHelpRequestStates.confirm)
    await state.update_data(
        manager_help_token=token,
        manager_help_text=request_text,
        manager_help_content_kind=content_kind,
        manager_help_source_chat_id=int(message.chat.id),
        manager_help_source_message_id=int(message.message_id),
        manager_help_sent=False,
        manager_help_preview_message_id=preview.message_id,
    )


@router.callback_query(ManagerHelpRequestStates.confirm, F.data.startswith("mhelp_cancel:"))
async def manager_help_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    token = _extract_support_token(callback.data, "mhelp_cancel:")
    data = await state.get_data()
    if token is None or data.get("manager_help_token") != token:
        await callback.answer("Эта кнопка устарела. Откройте раздел заново.", show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Обращение менеджеру отменено.")
        await _restore_seller_scrolls_or_start_menu(callback.message, callback.from_user.id)
    await callback.answer("Отменено.")


@router.callback_query(ManagerHelpRequestStates.confirm, F.data.startswith("mhelp_send:"))
async def manager_help_send(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    token = _extract_support_token(callback.data, "mhelp_send:")
    data = await state.get_data()
    if token is None or data.get("manager_help_token") != token:
        await callback.answer("Эта кнопка устарела. Откройте раздел заново.", show_alert=True)
        return
    if data.get("manager_help_sent"):
        await callback.answer("Обращение уже отправлено.")
        return
    config = get_config()
    rate_key = f"manager_help_send:{callback.from_user.id}"
    rate_token = acquire_rate_limit(
        rate_key,
        limit=1,
        window_sec=config.manager_help_send_cooldown_sec,
    )
    if rate_token is None:
        await callback.answer(
            f"Повторная отправка доступна раз в {config.manager_help_send_cooldown_sec} сек.",
            show_alert=True,
        )
        return
    manager_tg_user_id = int(data.get("manager_help_manager_tg_user_id") or 0)
    if manager_tg_user_id <= 0:
        await callback.answer("Не удалось определить менеджера компании.", show_alert=True)
        return
    u = callback.from_user
    name = f"{u.first_name or ''} {u.last_name or ''}".strip() or f"ID {u.id}"
    username_part = f", @{u.username}" if u.username else ""
    org_name = html.escape(str(data.get("manager_help_org_name") or "-"))
    org_inn = html.escape(str(data.get("manager_help_org_inn") or "-"))
    content_kind = str(data.get("manager_help_content_kind") or "text")
    source_chat_id = int(data.get("manager_help_source_chat_id") or 0)
    source_message_id = int(data.get("manager_help_source_message_id") or 0)
    request_text = html.escape(str(data.get("manager_help_text", "")).strip()[:2000])
    try:
        header = (
            "Запрос по усилению продаж от сотрудника:\n"
            f"Пользователь: {html.escape(name)}, ID: <code>{u.id}</code>{username_part}\n"
            f"Компания: {org_name} ({org_inn})\n"
        )
        if content_kind == "text":
            await callback.bot.send_message(
                manager_tg_user_id,
                header + f"\nТекст:\n<blockquote>{request_text}</blockquote>",
            )
        else:
            media_text = header + f"\nТип вложения: {html.escape(content_kind)}"
            if request_text:
                media_text += f"\nКомментарий:\n<blockquote>{request_text}</blockquote>"
            await callback.bot.send_message(manager_tg_user_id, media_text)
            await callback.bot.copy_message(
                chat_id=manager_tg_user_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
    except Exception:
        release_rate_limit(rate_key, rate_token)
        logger.exception("Failed to send manager help request")
        await callback.answer("Не удалось отправить обращение. Попробуйте позже.", show_alert=True)
        return
    await state.update_data(manager_help_sent=True)
    await state.clear()
    await callback.message.edit_text("Обращение отправлено вашему менеджеру.")
    await _restore_seller_scrolls_or_start_menu(callback.message, callback.from_user.id)
    await callback.answer("Отправлено.")


@router.callback_query(F.data.startswith("mhelp_cancel:"))
@router.callback_query(F.data.startswith("mhelp_send:"))
async def manager_help_stale(callback: CallbackQuery) -> None:
    await callback.answer("Этот запрос уже неактуален. Откройте раздел заново.", show_alert=True)


@router.callback_query(F.data == SUPPORT_CALLBACK)
async def support_request_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    await state.set_state(SupportRequestStates.wait_text)
    await state.set_data({})
    await callback.message.answer(
        "Опишите обращение или отправьте фото/видео/файл одним сообщением.\n"
        "После этого будет шаг подтверждения.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(SupportRequestStates.wait_text)
async def support_request_collect_text(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    if raw_text and raw_text in _SELLER_MENU_COMMANDS:
        await state.clear()
        await message.answer("Текущее обращение в поддержку отменено.")
        await _restore_seller_scrolls_or_start_menu(message, message.from_user.id)
        return
    content_kind, request_text = _extract_request_payload(message)
    if content_kind is None:
        await message.answer(
            "Отправьте текст, фото, видео, файл или другое вложение одним сообщением."
        )
        return
    token = secrets.token_urlsafe(8)
    preview = await message.answer(
        _request_preview_text("Проверьте обращение перед отправкой:", content_kind, request_text),
        reply_markup=support_confirm_keyboard(token),
    )
    await state.set_state(SupportRequestStates.confirm)
    await state.update_data(
        support_token=token,
        support_text=request_text,
        support_content_kind=content_kind,
        support_source_chat_id=int(message.chat.id),
        support_source_message_id=int(message.message_id),
        support_sent=False,
        support_preview_message_id=preview.message_id,
    )


@router.callback_query(SupportRequestStates.confirm, F.data.startswith("support_cancel:"))
async def support_request_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    token = _extract_support_token(callback.data, "support_cancel:")
    data = await state.get_data()
    if token is None or data.get("support_token") != token:
        await callback.answer("Эта кнопка устарела. Откройте поддержку заново.", show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Обращение отменено.")
        await _restore_seller_scrolls_or_start_menu(callback.message, callback.from_user.id)
    await callback.answer("Отменено.")


@router.callback_query(SupportRequestStates.confirm, F.data.startswith("support_send:"))
async def support_request_send(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    token = _extract_support_token(callback.data, "support_send:")
    data = await state.get_data()
    if token is None or data.get("support_token") != token:
        await callback.answer("Эта кнопка устарела. Откройте поддержку заново.", show_alert=True)
        return
    if data.get("support_sent"):
        await callback.answer("Обращение уже отправлено.")
        return
    config = get_config()
    rate_key = f"support_send:{callback.from_user.id}"
    rate_token = acquire_rate_limit(
        rate_key,
        limit=1,
        window_sec=config.support_send_cooldown_sec,
    )
    if rate_token is None:
        await callback.answer(
            f"Повторная отправка доступна раз в {config.support_send_cooldown_sec} сек.",
            show_alert=True,
        )
        return
    u = callback.from_user
    name = f"{u.first_name or ''} {u.last_name or ''}".strip() or f"ID {u.id}"
    username_part = f", @{u.username}" if u.username else ""
    content_kind = str(data.get("support_content_kind") or "text")
    source_chat_id = int(data.get("support_source_chat_id") or 0)
    source_message_id = int(data.get("support_source_message_id") or 0)
    request_text = html.escape(str(data.get("support_text", "")).strip()[:2000])
    try:
        header = (
            "Новое обращение в техподдержку:\n"
            f"Пользователь: {html.escape(name)}, ID: <code>{u.id}</code>{username_part}\n"
        )
        if content_kind == "text":
            await callback.bot.send_message(
                config.support_user_id,
                header + f"\nТекст:\n<blockquote>{request_text}</blockquote>",
            )
        else:
            media_text = header + f"\nТип вложения: {html.escape(content_kind)}"
            if request_text:
                media_text += f"\nКомментарий:\n<blockquote>{request_text}</blockquote>"
            await callback.bot.send_message(config.support_user_id, media_text)
            await callback.bot.copy_message(
                chat_id=config.support_user_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
    except Exception:
        release_rate_limit(rate_key, rate_token)
        logger.exception("Failed to send support request")
        await callback.answer("Не удалось отправить обращение. Попробуйте позже.", show_alert=True)
        return
    await state.update_data(support_sent=True)
    await state.clear()
    await callback.message.edit_text("Обращение отправлено. Техподдержка свяжется с вами.")
    await _restore_seller_scrolls_or_start_menu(callback.message, callback.from_user.id)
    await callback.answer("Отправлено.")


@router.callback_query(F.data.startswith("support_cancel:"))
@router.callback_query(F.data.startswith("support_send:"))
async def support_request_stale(callback: CallbackQuery) -> None:
    await callback.answer("Этот запрос уже неактуален. Откройте поддержку заново.", show_alert=True)
