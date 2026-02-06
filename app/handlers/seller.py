from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.config import get_config
from app.db import sqlite
from app.handlers.start import is_manager, show_seller_menu, show_seller_start
from app.keyboards.common import BACK_TEXT
from app.keyboards.seller import (
    SELLER_COMPANY_NO,
    SELLER_COMPANY_YES,
    SELLER_MENU_HELP,
    SELLER_MENU_PROFILE,
    SELLER_RETRY,
    SELLER_SUPPORT,
    seller_back_menu,
    seller_main_menu,
    seller_retry_menu,
    seller_start_menu,
)
from app.utils.security import verify_password
from app.utils.time import format_iso_human, now_utc_iso
from app.utils.validators import validate_inn

logger = logging.getLogger(__name__)

router = Router()


class SellerRegisterStates(StatesGroup):
    inn = State()
    password = State()


async def _send_error(message: Message) -> None:
    await message.answer("Произошла ошибка, попробуйте позже.", reply_markup=seller_back_menu())


async def _process_registration(
    message: Message, state: FSMContext, inn: str, password: str
) -> None:
    config = get_config()
    try:
        org = await sqlite.get_org_by_inn(config.db_path, inn)
        if not org or not verify_password(password, org["password_hash"]):
            support_link = (
                f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
            )
            await message.answer(
                "Данные неверные.\n"
                "Проверьте ИНН и пароль. Если пароль не подходит — обратитесь в техподдержку.\n"
                f"Контакт: {support_link}",
                reply_markup=seller_retry_menu(),
            )
            return
        registered_at = now_utc_iso()
        await sqlite.create_user(
            config.db_path,
            tg_user_id=message.from_user.id,
            org_id=int(org["id"]),
            registered_at=registered_at,
            last_seen_at=registered_at,
        )
        await sqlite.log_audit(
            config.db_path,
            actor_tg_user_id=message.from_user.id,
            actor_role="seller",
            action="SELLER_REGISTER",
            payload={"org_id": int(org["id"]), "inn": inn},
        )
        await state.clear()
        await message.answer("Регистрация завершена ✅")
        await show_seller_menu(message)
    except Exception:
        logger.exception("Failed to register seller")
        await _send_error(message)


@router.message(F.text.in_({SELLER_COMPANY_YES, "Да", "ДА", "да"}))
async def seller_register_start(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await state.clear()
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(F.text.in_({SELLER_COMPANY_NO, "Нет", "НЕТ", "нет"}))
async def seller_company_no(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    await state.clear()
    config = get_config()
    support_link = f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
    await message.answer(
        "Для регистрации компании обратитесь в техподдержку.\n"
        f"Контакт: {support_link}",
        reply_markup=seller_back_menu(),
    )


@router.message(SellerRegisterStates.inn, F.text == BACK_TEXT)
async def seller_register_inn_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_seller_start(message)


@router.message(SellerRegisterStates.inn)
async def seller_register_inn_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ИНН или нажмите ⬅️ Назад.")
        return
    inn = message.text.strip()
    if not validate_inn(inn):
        await message.answer("ИНН должен содержать 10 или 12 цифр", reply_markup=seller_back_menu())
        return
    config = get_config()
    org = await sqlite.get_org_by_inn(config.db_path, inn)
    if not org:
        support_link = f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
        await message.answer(
            "Организация не найдена.\n"
            "Проверьте ИНН или обратитесь в техподдержку для регистрации организации.\n"
            f"Контакт: {support_link}",
            reply_markup=seller_back_menu(),
        )
        return
    await state.update_data(inn=inn)
    await state.set_state(SellerRegisterStates.password)
    await message.answer("Введите пароль организации.", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.password, F.text == BACK_TEXT)
async def seller_register_password_back(message: Message, state: FSMContext) -> None:
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(SellerRegisterStates.password)
async def seller_register_password_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите пароль или нажмите ⬅️ Назад.")
        return
    password = message.text.strip()
    data = await state.get_data()
    inn = data.get("inn")
    if not inn:
        await state.set_state(SellerRegisterStates.inn)
        await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())
        return
    await _process_registration(message, state, inn, password)


@router.message(F.text == SELLER_RETRY)
async def seller_retry(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await state.set_state(SellerRegisterStates.inn)
    await message.answer("Введите ИНН организации (10 или 12 цифр).", reply_markup=seller_back_menu())


@router.message(F.text == SELLER_SUPPORT)
async def seller_support(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    support_link = f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
    await message.answer(f"Контакт поддержки: {support_link}", reply_markup=seller_retry_menu())


@router.message(F.text == SELLER_MENU_PROFILE)
async def seller_profile(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if not user:
        await show_seller_start(message)
        return
    await sqlite.update_last_seen(config.db_path, message.from_user.id)
    registered_at = format_iso_human(user["registered_at"])
    await sqlite.log_audit(
        config.db_path,
        actor_tg_user_id=message.from_user.id,
        actor_role="seller",
        action="VIEW_PROFILE",
        payload=None,
    )
    await message.answer(
        "Профиль:\n"
        f"ID: {message.from_user.id}\n"
        f"Дата регистрации: {registered_at}",
        reply_markup=seller_back_menu(),
    )


@router.message(F.text == SELLER_MENU_HELP)
async def seller_help(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    support_link = f"<a href=\"tg://user?id={config.support_user_id}\">техподдержку</a>"
    await message.answer(
        "Бот помогает зарегистрировать продавцов через ИНН и пароль.\n"
        f"Если возникли сложности, напишите в {support_link}.",
        reply_markup=seller_back_menu(),
    )


@router.message(F.text == BACK_TEXT)
async def seller_back(message: Message) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await show_seller_menu(message)
        return
    await show_seller_start(message)


@router.message()
async def seller_fallback(message: Message, state: FSMContext) -> None:
    if is_manager(message.from_user.id):
        return
    config = get_config()
    user = await sqlite.get_user_by_tg_id(config.db_path, message.from_user.id)
    if user:
        await message.answer("Пожалуйста, выберите пункт меню.", reply_markup=seller_main_menu())
    else:
        await message.answer("Пожалуйста, выберите «Да» или «Нет».", reply_markup=seller_start_menu())
