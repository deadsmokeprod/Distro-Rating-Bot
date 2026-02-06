from datetime import datetime

import bcrypt
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.config import (
    ROLE_ADMIN,
    ROLE_MINI_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    Config,
)
from bot.db.repo import (
    create_user,
    get_organization_by_inn,
    get_user_by_tg,
    log_audit,
)
from bot.keyboards.menu import build_menu

router = Router()


class RegistrationState(StatesGroup):
    choose_role = State()
    enter_inn = State()
    enter_password = State()
    enter_fullname = State()


ROLE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Дистрибьютер"), KeyboardButton(text="Продавец")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


@router.message(CommandStart(), flags={"allow_unauthorized": True})
async def cmd_start(message: Message, state: FSMContext, config: Config, session_factory):
    user = None
    async with session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user:
            if message.from_user.id in config.super_admin_ids:
                user = await create_user(
                    session, message.from_user.id, ROLE_SUPER_ADMIN, message.from_user.full_name, None
                )
            elif message.from_user.id in config.admin_ids:
                user = await create_user(
                    session, message.from_user.id, ROLE_ADMIN, message.from_user.full_name, None
                )
    if user:
        await message.answer("MJOLNIR RATE DISTR", reply_markup=build_menu(config.menu_config.get(user.role, [])))
        return
    await message.answer("MJOLNIR RATE DISTR")
    await message.answer("Выберите роль:", reply_markup=ROLE_KEYBOARD)
    await state.set_state(RegistrationState.choose_role)


@router.message(RegistrationState.choose_role, flags={"allow_unauthorized": True})
async def choose_role(message: Message, state: FSMContext):
    if message.text not in {"Дистрибьютер", "Продавец"}:
        await message.answer("Пожалуйста, выберите роль кнопкой.")
        return
    role = ROLE_MINI_ADMIN if message.text == "Дистрибьютер" else ROLE_USER
    await state.update_data(role=role)
    await message.answer("Введите ИНН организации:", reply_markup=None)
    await state.set_state(RegistrationState.enter_inn)


@router.message(RegistrationState.enter_inn, flags={"allow_unauthorized": True})
async def enter_inn(message: Message, state: FSMContext, config: Config, session_factory):
    inn = (message.text or "").strip()
    async with session_factory() as session:
        org = await get_organization_by_inn(session, inn)
    if not org:
        await message.answer(
            "Организация ещё не зарегистрирована. Свяжитесь с менеджером: "
            f"tg://user?id={config.registration_contact_tg_id}"
        )
        await state.clear()
        return
    await state.update_data(inn=inn)
    await message.answer("Введите пароль организации:")
    await state.set_state(RegistrationState.enter_password)


@router.message(RegistrationState.enter_password, flags={"allow_unauthorized": True})
async def enter_password(message: Message, state: FSMContext, session_factory):
    data = await state.get_data()
    inn = data.get("inn")
    password = message.text or ""
    async with session_factory() as session:
        org = await get_organization_by_inn(session, inn)
        success = False
        if org and bcrypt.checkpw(password.encode("utf-8"), org.password_hash.encode("utf-8")):
            success = True
        await log_audit(
            session,
            message.from_user.id,
            None,
            "login_attempt",
            {
                "inn": inn,
                "pwd_mask": f"****{password[-4:]}",
                "success": success,
            },
        )
    if not success:
        await message.answer("Неверный пароль. Попробуйте снова.")
        return
    await message.answer("Введите ФИО (обязательно):")
    await state.set_state(RegistrationState.enter_fullname)


@router.message(RegistrationState.enter_fullname, flags={"allow_unauthorized": True})
async def enter_fullname(message: Message, state: FSMContext, config: Config, session_factory):
    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer("ФИО обязательно для регистрации.")
        return
    data = await state.get_data()
    inn = data.get("inn")
    role = data.get("role")
    async with session_factory() as session:
        org = await get_organization_by_inn(session, inn)
        if not org:
            await message.answer("Организация не найдена.")
            await state.clear()
            return
        await create_user(session, message.from_user.id, role, full_name, org.id)
    await message.answer(
        "Регистрация завершена!", reply_markup=build_menu(config.menu_config.get(role, []))
    )
    await state.clear()
