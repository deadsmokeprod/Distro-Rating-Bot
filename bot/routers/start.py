from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import load_config
from bot.db.repo import create_user, get_org_by_inn, log_audit
from bot.keyboards.menu import main_menu, registration_choice
from bot.services.security import check_password


router = Router()


class RegistrationStates(StatesGroup):
    choosing_role = State()
    entering_inn = State()
    entering_password = State()
    entering_full_name = State()


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, session: AsyncSession, user=None):
    await state.clear()
    if user:
        await message.answer("MJOLNIR RATE DISTR", reply_markup=main_menu(user.role))
        return
    config = load_config()
    if message.from_user.id in config.super_admin_ids:
        user = await create_user(
            session=session,
            tg_id=message.from_user.id,
            role="SUPER_ADMIN",
            full_name=message.from_user.full_name,
            org_id=None,
        )
        await message.answer("MJOLNIR RATE DISTR", reply_markup=main_menu(user.role))
        return
    if message.from_user.id in config.admin_ids:
        user = await create_user(
            session=session,
            tg_id=message.from_user.id,
            role="ADMIN",
            full_name=message.from_user.full_name,
            org_id=None,
        )
        await message.answer("MJOLNIR RATE DISTR", reply_markup=main_menu(user.role))
        return
    await message.answer(
        "MJOLNIR RATE DISTR\nВыберите роль:",
        reply_markup=registration_choice(),
    )
    await state.set_state(RegistrationStates.choosing_role)


@router.message(RegistrationStates.choosing_role)
async def choose_role(message: Message, state: FSMContext):
    if message.text not in {"Дистрибьютер", "Продавец"}:
        await message.answer("Пожалуйста, выберите роль кнопкой ниже.")
        return
    role = "MINI_ADMIN" if message.text == "Дистрибьютер" else "USER"
    await state.update_data(role=role)
    await message.answer("Введите ИНН организации:")
    await state.set_state(RegistrationStates.entering_inn)


@router.message(RegistrationStates.entering_inn)
async def enter_inn(message: Message, state: FSMContext, session: AsyncSession):
    inn = message.text.strip()
    org = await get_org_by_inn(session, inn)
    if not org:
        config = load_config()
        await message.answer(
            "Организация ещё не зарегистрирована. Свяжитесь с менеджером: "
            f"{config.registration_contact_tg_id}"
        )
        await state.clear()
        return
    await state.update_data(inn=inn, org_id=org.id)
    await message.answer("Введите пароль организации:")
    await state.set_state(RegistrationStates.entering_password)


@router.message(RegistrationStates.entering_password)
async def enter_password(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    inn = data["inn"]
    org = await get_org_by_inn(session, inn)
    password = message.text.strip()
    success = False
    if org and check_password(password, org.password_hash):
        success = True
        await state.update_data(org_id=org.id)
        await message.answer("Введите ФИО:")
        await state.set_state(RegistrationStates.entering_full_name)
    else:
        await message.answer("Неверный пароль организации.")
        await state.clear()
    await log_audit(
        session,
        tg_id=message.from_user.id,
        role=None,
        action="login_attempt",
        meta={"inn": inn, "pwd_mask": f"****{password[-4:]}", "success": success},
    )


@router.message(RegistrationStates.entering_full_name)
async def enter_full_name(message: Message, state: FSMContext, session: AsyncSession):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("ФИО обязательно.")
        return
    data = await state.get_data()
    user = await create_user(
        session,
        tg_id=message.from_user.id,
        role=data["role"],
        full_name=full_name,
        org_id=data["org_id"],
    )
    await state.clear()
    await message.answer("Регистрация завершена!", reply_markup=main_menu(user.role))
