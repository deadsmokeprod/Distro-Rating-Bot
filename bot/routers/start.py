from __future__ import annotations

from typing import Dict

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.config import load_config
from bot.db.engine import get_sessionmaker
from bot.db.repo import add_audit_log, create_user, get_org_by_inn, get_user_by_tg_id, update_user_role
from bot.keyboards.menu import build_menu
from bot.services.security import mask_password, verify_password

router = Router()


class RegistrationState(StatesGroup):
    choose_role = State()
    input_inn = State()
    input_password = State()
    input_full_name = State()


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    config = load_config()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await get_user_by_tg_id(session, message.from_user.id)
        expected_role = None
        if message.from_user.id in config.super_admin_ids:
            expected_role = "SUPER_ADMIN"
        elif message.from_user.id in config.admin_ids:
            expected_role = "ADMIN"
        if user:
            if expected_role and user.role != expected_role:
                await update_user_role(session, message.from_user.id, expected_role)
                user.role = expected_role
            menu = build_menu(config.menu_config, user.role)
            await message.answer("MJOLNIR RATE DISTR", reply_markup=menu)
            return
        if expected_role:
            user = await create_user(
                session,
                message.from_user.id,
                expected_role,
                message.from_user.full_name,
                None,
            )
            menu = build_menu(config.menu_config, user.role)
            await message.answer("MJOLNIR RATE DISTR", reply_markup=menu)
            return
    await message.answer("MJOLNIR RATE DISTR")
    await message.answer(
        "Выберите роль:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Дистрибьютер"), KeyboardButton(text="Продавец")]],
            resize_keyboard=True,
        ),
    )
    await state.set_state(RegistrationState.choose_role)


@router.message(RegistrationState.choose_role)
async def choose_role_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text not in {"дистрибьютер", "продавец"}:
        await message.answer("Пожалуйста, выберите роль: Дистрибьютер или Продавец.")
        return
    role = "MINI_ADMIN" if text == "дистрибьютер" else "USER"
    await state.update_data(role=role)
    await message.answer("Введите ИНН организации:")
    await state.set_state(RegistrationState.input_inn)


@router.message(RegistrationState.input_inn)
async def input_inn_handler(message: Message, state: FSMContext) -> None:
    config = load_config()
    inn = (message.text or "").strip()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_inn(session, inn)
    if not org:
        await message.answer(
            f"Организация ещё не зарегистрирована. Свяжитесь с менеджером: {config.registration_contact_tg_id}"
        )
        await state.clear()
        return
    await state.update_data(inn=inn)
    await message.answer("Введите пароль организации:")
    await state.set_state(RegistrationState.input_password)


@router.message(RegistrationState.input_password)
async def input_password_handler(message: Message, state: FSMContext) -> None:
    config = load_config()
    password = (message.text or "").strip()
    data = await state.get_data()
    inn = data.get("inn")
    if not inn:
        await state.clear()
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_inn(session, inn)
        if not org:
            await message.answer(
                f"Организация ещё не зарегистрирована. Свяжитесь с менеджером: {config.registration_contact_tg_id}"
            )
            await state.clear()
            return
        success = verify_password(password, org.password_hash)
        await add_audit_log(
            session,
            message.from_user.id,
            None,
            "login_attempt",
            {"inn": inn, "pwd_mask": mask_password(password), "success": success},
        )
    if not success:
        await message.answer("Неверный пароль организации.")
        await state.clear()
        return
    await message.answer("Введите ваше ФИО:")
    await state.set_state(RegistrationState.input_full_name)


@router.message(RegistrationState.input_full_name)
async def input_full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer("ФИО обязательно. Введите ваше ФИО:")
        return
    data = await state.get_data()
    role = data.get("role")
    inn = data.get("inn")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        org = await get_org_by_inn(session, inn)
        if not org:
            await message.answer("Организация не найдена.")
            await state.clear()
            return
        await create_user(session, message.from_user.id, role, full_name, org.id)
    menu = build_menu(load_config().menu_config, role)
    await message.answer("Регистрация завершена.", reply_markup=menu)
    await state.clear()
