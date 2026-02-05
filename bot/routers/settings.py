from __future__ import annotations

import secrets

from sqlalchemy.exc import IntegrityError

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.config import load_config
from bot.db.engine import get_sessionmaker
from bot.db.repo import create_organization, get_ticket_stats, update_payout_details
from bot.keyboards.menu import BUTTON_LABELS, build_menu
from bot.services.audit import log_menu_click
from bot.services.security import hash_password
from bot.services.time_utils import get_last_closed_month
from bot.services.erp_sync import sync_erp

router = Router()


class SettingsState(StatesGroup):
    input_inn = State()
    input_name = State()
    input_payout = State()


def _settings_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    buttons = []
    if is_admin:
        buttons.extend([
            [KeyboardButton(text="Регистрация дистрибьютера")],
            [KeyboardButton(text="Статистика по обращениям")],
            [KeyboardButton(text="Принудительно обновить данные из 1С")],
        ])
    buttons.append([KeyboardButton(text="Указание реквизитов для выплат")])
    buttons.append([KeyboardButton(text="Назад")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


@router.message(lambda m: m.text == BUTTON_LABELS["SETTINGS"])
async def settings_menu(message: Message, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "SETTINGS")
    is_admin = db_user.role in {"SUPER_ADMIN", "ADMIN"}
    await message.answer("Настройки:", reply_markup=_settings_keyboard(is_admin))


@router.message(lambda m: m.text == "Назад")
async def settings_back(message: Message, db_user) -> None:
    menu = build_menu(load_config().menu_config, db_user.role)
    await message.answer("Главное меню", reply_markup=menu)


@router.message(lambda m: m.text == "Регистрация дистрибьютера")
async def register_distributor_start(message: Message, state: FSMContext, db_user) -> None:
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await log_menu_click(message, db_user.role, "REGISTER_ORG")
    await message.answer("Введите ИНН организации:")
    await state.set_state(SettingsState.input_inn)


@router.message(SettingsState.input_inn)
async def register_distributor_inn(message: Message, state: FSMContext) -> None:
    inn = (message.text or "").strip()
    if not inn:
        await message.answer("ИНН обязателен. Введите ИНН:")
        return
    await state.update_data(inn=inn)
    await message.answer("Введите наименование организации:")
    await state.set_state(SettingsState.input_name)


@router.message(SettingsState.input_name)
async def register_distributor_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название обязательно. Введите наименование:")
        return
    data = await state.get_data()
    inn = data.get("inn")
    password_plain = secrets.token_urlsafe(8)
    password_hash = hash_password(password_plain)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            await create_organization(session, inn, name, password_hash, message.from_user.id)
        except IntegrityError:
            await session.rollback()
            await message.answer("Организация с таким ИНН уже существует.")
            await state.clear()
            return
    await message.answer(
        f"Организация зарегистрирована. Пароль (показан один раз): {password_plain}"
    )
    await state.clear()


@router.message(lambda m: m.text == "Статистика по обращениям")
async def support_stats(message: Message, db_user) -> None:
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await log_menu_click(message, db_user.role, "SUPPORT_STATS")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        active, closed = await get_ticket_stats(session)
    await message.answer(f"Активные обращения: {active}\nЗакрытые обращения: {closed}")


@router.message(lambda m: m.text == "Указание реквизитов для выплат")
async def payout_details_start(message: Message, state: FSMContext, db_user) -> None:
    await log_menu_click(message, db_user.role if db_user else None, "PAYOUT_DETAILS")
    await message.answer("Введите реквизиты для выплат:")
    await state.set_state(SettingsState.input_payout)


@router.message(SettingsState.input_payout)
async def payout_details_finish(message: Message, state: FSMContext, db_user) -> None:
    details = (message.text or "").strip()
    if not details:
        await message.answer("Реквизиты не могут быть пустыми. Введите текст:")
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await update_payout_details(session, db_user.id, details)
    await message.answer("Реквизиты сохранены.")
    await state.clear()


@router.message(lambda m: m.text == "Принудительно обновить данные из 1С")
async def manual_sync(message: Message, db_user) -> None:
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await log_menu_click(message, db_user.role, "ERP_SYNC")
    config = load_config()
    month_key, start, end = get_last_closed_month(config.timezone)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        count = await sync_erp(session, start, end, month_key)
    await message.answer(f"Синхронизация завершена. Обработано строк: {count}")
