import secrets

import bcrypt
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from bot.config import BUTTONS, ROLE_ADMIN, ROLE_SUPER_ADMIN
from bot.db.repo import (
    create_organization,
    log_audit,
    set_payout_details,
)

router = Router()

SETTINGS_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Регистрация дистрибьютера")],
        [KeyboardButton(text="Статистика по обращениям")],
        [KeyboardButton(text="Принудительно обновить данные из 1С")],
        [KeyboardButton(text="Указание реквизитов для выплат")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


class SettingsState(StatesGroup):
    org_inn = State()
    org_name = State()
    payout_details = State()


@router.message(F.text == BUTTONS["SETTINGS"])
async def settings_menu(message: Message):
    await message.answer("Выберите действие:", reply_markup=SETTINGS_MENU)


@router.message(F.text == "Регистрация дистрибьютера")
async def register_distributor_start(message: Message, state: FSMContext, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Введите ИНН организации:")
    await state.set_state(SettingsState.org_inn)


@router.message(SettingsState.org_inn)
async def register_distributor_inn(message: Message, state: FSMContext, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        await state.clear()
        return
    await state.update_data(inn=(message.text or "").strip())
    await message.answer("Введите наименование организации:")
    await state.set_state(SettingsState.org_name)


@router.message(SettingsState.org_name)
async def register_distributor_name(message: Message, state: FSMContext, session_factory, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        await state.clear()
        return
    data = await state.get_data()
    inn = data.get("inn")
    name = (message.text or "").strip()
    password_plain = secrets.token_urlsafe(8)
    password_hash = bcrypt.hashpw(password_plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    async with session_factory() as session:
        await create_organization(session, inn, name, password_hash, user.tg_id)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "REGISTER_ORG"},
        )
    await message.answer(
        f"Организация создана. Пароль (показан один раз): {password_plain}"
    )
    await state.clear()


@router.message(F.text == "Статистика по обращениям")
async def support_stats(message: Message, session_factory, user):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        return
    async with session_factory() as session:
        active = await session.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE status = 'OPEN'"
        )
        closed = await session.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE status = 'CLOSED'"
        )
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "SUPPORT_STATS"},
        )
    await message.answer(
        f"Активные обращения: {active.scalar_one()}\nЗакрытые обращения: {closed.scalar_one()}"
    )


@router.message(F.text == "Принудительно обновить данные из 1С")
async def manual_sync(message: Message, session_factory, user, config):
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        await message.answer("Недостаточно прав.")
        return
    from bot.services.sync_service import sync_erp

    await message.answer("Запускаю синхронизацию...")
    inserted = await sync_erp(config, session_factory)
    await message.answer(f"Синхронизация завершена. Обработано строк: {inserted}")


@router.message(F.text == "Указание реквизитов для выплат")
async def payout_details_start(message: Message, state: FSMContext):
    await message.answer("Введите реквизиты для выплат:")
    await state.set_state(SettingsState.payout_details)


@router.message(SettingsState.payout_details)
async def payout_details_save(message: Message, state: FSMContext, session_factory, user):
    details = (message.text or "").strip()
    async with session_factory() as session:
        await set_payout_details(session, user.id, details)
        await log_audit(
            session,
            user.tg_id,
            user.role,
            "menu_click",
            {"button": "PAYOUT_DETAILS"},
        )
    await message.answer("Реквизиты сохранены.")
    await state.clear()
