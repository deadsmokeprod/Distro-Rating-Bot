from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import bcrypt
from ..config import Config
from ..db.repo import get_user_by_tg, create_user, get_org_by_inn, log_audit
from ..keyboards.menu import build_menu


router = Router()


class RegistrationState(StatesGroup):
    choose_role = State()
    enter_inn = State()
    enter_password = State()
    enter_full_name = State()


ROLE_BUTTONS = {
    "Дистрибьютер": "MINI_ADMIN",
    "Продавец": "USER",
}


@router.message(CommandStart(), flags={"allow_unauth": True})
async def start_command(message: Message, state: FSMContext, config: Config, db_user, session):
    await state.clear()
    if db_user:
        buttons = config.menu_config.get(db_user.role, [])
        await message.answer("MJOLNIR RATE DISTR", reply_markup=build_menu(buttons))
        return
    tg_id = message.from_user.id
    if tg_id in config.super_admin_ids:
        user = await create_user(
            session=session,
            tg_id=tg_id,
            role="SUPER_ADMIN",
            full_name=message.from_user.full_name,
            org_id=None,
        )
        buttons = config.menu_config.get(user.role, [])
        await message.answer("MJOLNIR RATE DISTR", reply_markup=build_menu(buttons))
        return
    if tg_id in config.admin_ids:
        user = await create_user(
            session=session,
            tg_id=tg_id,
            role="ADMIN",
            full_name=message.from_user.full_name,
            org_id=None,
        )
        buttons = config.menu_config.get(user.role, [])
        await message.answer("MJOLNIR RATE DISTR", reply_markup=build_menu(buttons))
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Дистрибьютер"), KeyboardButton(text="Продавец")]],
        resize_keyboard=True,
    )
    await message.answer("MJOLNIR RATE DISTR\nВыберите роль для регистрации:", reply_markup=keyboard)
    await state.set_state(RegistrationState.choose_role)


@router.message(RegistrationState.choose_role, F.text.in_(ROLE_BUTTONS.keys()), flags={"allow_unauth": True})
async def choose_role(message: Message, state: FSMContext):
    await state.update_data(role=ROLE_BUTTONS[message.text])
    await message.answer("Введите ИНН организации:")
    await state.set_state(RegistrationState.enter_inn)


@router.message(RegistrationState.enter_inn, flags={"allow_unauth": True})
async def enter_inn(message: Message, state: FSMContext, config: Config, db_user, session):
    inn = message.text.strip()
    await state.update_data(inn=inn)
    org = await get_org_by_inn(session, inn)
    if not org:
        await message.answer(
            f"Организация ещё не зарегистрирована. Свяжитесь с менеджером: {config.registration_contact_tg_id}"
        )
        await state.clear()
        return
    await message.answer("Введите пароль организации:")
    await state.set_state(RegistrationState.enter_password)


@router.message(RegistrationState.enter_password, flags={"allow_unauth": True})
async def enter_password(message: Message, state: FSMContext, config: Config, db_user, session):
    data = await state.get_data()
    inn = data.get("inn")
    password = message.text.strip()
    org = await get_org_by_inn(session, inn)
    mask = f"****{password[-4:]}" if len(password) >= 4 else "****"
    if not org or not bcrypt.checkpw(password.encode(), org.password_hash.encode()):
        await log_audit(
            session,
            message.from_user.id,
            None,
            "login_attempt",
            {"inn": inn, "pwd_mask": mask, "success": False},
        )
        await message.answer("Неверный пароль. Попробуйте снова через /start")
        await state.clear()
        return
    await log_audit(
        session,
        message.from_user.id,
        None,
        "login_attempt",
        {"inn": inn, "pwd_mask": mask, "success": True},
    )
    await message.answer("Введите ФИО (обязательно):")
    await state.set_state(RegistrationState.enter_full_name)


@router.message(RegistrationState.enter_full_name, flags={"allow_unauth": True})
async def enter_full_name(message: Message, state: FSMContext, config: Config, db_user, session):
    full_name = message.text.strip()
    data = await state.get_data()
    role = data.get("role")
    inn = data.get("inn")
    if not full_name:
        await message.answer("ФИО обязательно. Введите ФИО:")
        return
    org = await get_org_by_inn(session, inn)
    user = await create_user(
        session=session,
        tg_id=message.from_user.id,
        role=role,
        full_name=full_name,
        org_id=org.id if org else None,
    )
    buttons = config.menu_config.get(user.role, [])
    await message.answer("Регистрация завершена.", reply_markup=build_menu(buttons))
    await state.clear()
