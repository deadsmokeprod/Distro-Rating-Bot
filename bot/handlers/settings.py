from __future__ import annotations

import logging
from datetime import datetime

import bcrypt
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.constants import (
    ORG_ADD,
    ORG_LIST,
    ROLE_SUPER_ADMIN,
    SETTINGS_ORGS,
    SETTINGS_SYNC_NOW,
)
from bot.db.models import Organization, User
from bot.handlers.common import is_back, set_menu, show_main_menu
from bot.keyboards import organizations_menu, settings_menu
from bot.services.erp import ErpSyncError, fetch_sales, record_sync_error, record_sync_success, upsert_sales
from bot.services.users import get_user
from bot.states import MenuStates, OrganizationStates

logger = logging.getLogger(__name__)

router = Router()


async def show_settings_menu(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    if user.role != ROLE_SUPER_ADMIN:
        await show_main_menu(message, state, user)
        return
    await set_menu(state, MenuStates.settings_menu)
    await message.answer("Настройки:", reply_markup=settings_menu())


async def show_organizations_menu(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    if user.role != ROLE_SUPER_ADMIN:
        await show_main_menu(message, state, user)
        return
    await set_menu(state, MenuStates.org_menu)
    await message.answer("Организации:", reply_markup=organizations_menu())


@router.message(lambda message: message.text == SETTINGS_SYNC_NOW)
async def sync_now(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    user = await get_user(session, message.from_user.id)
    if not user or user.role != ROLE_SUPER_ADMIN:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Запущена синхронизация...")
    try:
        sales = await fetch_sales(
            config.erp_url,
            config.erp_username,
            config.erp_password,
        )
        added, updated = await upsert_sales(session, sales)
        await record_sync_success(session)
        await session.commit()
        await message.answer(f"✅ Синхронизация завершена: добавлено {added}, обновлено {updated}.")
    except ErpSyncError as exc:
        await record_sync_error(session, str(exc))
        await session.commit()
        logger.exception("ERP sync error")
        await message.answer("Ошибка синхронизации ERP. Попробуйте позже.")
    except SQLAlchemyError:
        logger.exception("DB error during sync")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(lambda message: message.text == SETTINGS_ORGS)
async def settings_orgs(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден. Введите /start.")
        return
    await show_organizations_menu(message, state, session, user)


@router.message(lambda message: message.text == ORG_LIST)
async def list_orgs(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user or user.role != ROLE_SUPER_ADMIN:
        await message.answer("Недостаточно прав.")
        return
    result = await session.execute(select(Organization).order_by(Organization.name.asc()))
    orgs = result.scalars().all()
    if not orgs:
        await message.answer("Организации не найдены.")
        return
    lines = [f"{org.inn} — {org.name}" for org in orgs]
    await message.answer("\n".join(lines))


@router.message(lambda message: message.text == ORG_ADD)
async def add_org_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user(session, message.from_user.id)
    if not user or user.role != ROLE_SUPER_ADMIN:
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(OrganizationStates.add_inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр):", reply_markup=organizations_menu())


@router.message(OrganizationStates.add_inn)
async def add_org_inn(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = message.text.strip()
    if is_back(text):
        user = await get_user(session, message.from_user.id)
        if user:
            await show_organizations_menu(message, state, session, user)
        return
    if not text.isdigit() or len(text) not in (10, 12):
        await message.answer("ИНН должен быть 10 или 12 цифр.")
        return
    existing = await session.get(Organization, text)
    if existing:
        await message.answer("Организация с таким ИНН уже создана.")
        return
    await state.update_data(org_inn=text)
    await state.set_state(OrganizationStates.add_name)
    await message.answer("Введите название организации:")


@router.message(OrganizationStates.add_name)
async def add_org_name(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if is_back(text):
        await state.set_state(OrganizationStates.add_inn)
        await message.answer("Введите ИНН организации (10 или 12 цифр):")
        return
    if not text:
        await message.answer("Название не может быть пустым.")
        return
    await state.update_data(org_name=text)
    await state.set_state(OrganizationStates.add_code)
    await message.answer("Введите код доступа для сотрудников:")


@router.message(OrganizationStates.add_code)
async def add_org_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = message.text.strip()
    if is_back(text):
        await state.set_state(OrganizationStates.add_name)
        await message.answer("Введите название организации:")
        return
    if not text:
        await message.answer("Код доступа не может быть пустым.")
        return
    data = await state.get_data()
    org_inn = data.get("org_inn")
    org_name = data.get("org_name")
    try:
        hashed = bcrypt.hashpw(text.encode(), bcrypt.gensalt()).decode()
        org = Organization(inn=org_inn, name=org_name, access_hash=hashed, created_at=datetime.utcnow())
        session.add(org)
        await session.commit()
        await message.answer("Организация добавлена.")
    except SQLAlchemyError:
        logger.exception("DB error while adding organization")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")
    user = await get_user(session, message.from_user.id)
    if user:
        await show_organizations_menu(message, state, session, user)
