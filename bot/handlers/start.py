from __future__ import annotations

import logging

import bcrypt
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..keyboards import BACK_TEXT, back_only, main_menu
from ..models import Organization, User
from ..states import RegistrationStates

logger = logging.getLogger(__name__)

router = Router()


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


@router.message(F.text == "/start")
async def start(message: Message, state: FSMContext, session: AsyncSession, config: Config) -> None:
    await state.clear()
    try:
        user = await _get_user(session, message.from_user.id)
        if user:
            is_super_admin = user.role == "SUPER_ADMIN"
            await message.answer("Вы уже зарегистрированы.", reply_markup=main_menu(is_super_admin))
            return
    except SQLAlchemyError:
        logger.exception("DB error in start")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")
        return

    await _prompt_name(message, state)


async def _prompt_name(message: Message, state: FSMContext) -> None:
    await message.answer("Введите ваше имя (2-64 символа):", reply_markup=back_only())
    await state.set_state(RegistrationStates.full_name)


@router.message(RegistrationStates.full_name, F.text == BACK_TEXT)
async def registration_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _prompt_name(message, state)


@router.message(RegistrationStates.full_name)
async def registration_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 64:
        await message.answer("Имя должно быть от 2 до 64 символов.")
        return
    await state.update_data(full_name=name)
    await message.answer("Введите код организации:", reply_markup=back_only())
    await state.set_state(RegistrationStates.organization_code)


@router.message(RegistrationStates.organization_code, F.text == BACK_TEXT)
async def registration_code_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _prompt_name(message, state)


@router.message(RegistrationStates.organization_code)
async def registration_code(message: Message, state: FSMContext, session: AsyncSession, config: Config) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer("Код не может быть пустым.")
        return
    data = await state.get_data()
    full_name = data.get("full_name")
    try:
        org_result = await session.execute(select(Organization))
        organizations = org_result.scalars().all()
        matched = None
        for org in organizations:
            if bcrypt.checkpw(code.encode("utf-8"), org.access_hash.encode("utf-8")):
                matched = org
                break
        if not matched:
            await message.answer("Код неверный, попробуйте ещё раз.", reply_markup=back_only())
            return
        role = "SUPER_ADMIN" if message.from_user.id in config.super_admin_ids else "SELLER"
        user = User(tg_id=message.from_user.id, full_name=full_name, role=role, organization_inn=matched.inn)
        session.add(user)
        await session.commit()
        await state.clear()
        await message.answer("Регистрация завершена.", reply_markup=main_menu(role == "SUPER_ADMIN"))
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("DB error during registration")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")
