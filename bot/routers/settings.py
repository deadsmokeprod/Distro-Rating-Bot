import secrets
import bcrypt
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from ..keyboards.menu import BUTTON_LABELS, build_menu
from ..db.repo import create_org, log_audit, get_support_stats, update_user_payout_details
from ..services.time_utils import get_last_closed_month, month_range
from ..services.erp_client import ErpClient
from ..db.repo import upsert_erp_sales

router = Router()


ADMIN_SETTINGS = [
    "Регистрация дистрибьютера",
    "Статистика по обращениям",
    "Принудительно обновить данные из 1С",
]
USER_SETTINGS = [
    "Указание реквизитов для выплат",
]


class OrgRegistrationState(StatesGroup):
    enter_inn = State()
    enter_name = State()


class PayoutState(StatesGroup):
    enter_details = State()


@router.message(F.text == BUTTON_LABELS["SETTINGS"])
async def settings_menu(message: Message, db_user, config, session):
    await log_audit(session, message.from_user.id, db_user.role, "menu_click", {"button": "SETTINGS"})
    buttons = []
    if db_user.role in {"SUPER_ADMIN", "ADMIN"}:
        buttons.extend(ADMIN_SETTINGS)
    buttons.extend(USER_SETTINGS)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn)] for btn in buttons], resize_keyboard=True
    )
    await message.answer("Выберите пункт настроек:", reply_markup=keyboard)


@router.message(F.text == "Регистрация дистрибьютера")
async def register_org_start(message: Message, state: FSMContext, db_user):
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Введите ИНН организации:")
    await state.set_state(OrgRegistrationState.enter_inn)


@router.message(OrgRegistrationState.enter_inn)
async def register_org_inn(message: Message, state: FSMContext):
    await state.update_data(inn=message.text.strip())
    await message.answer("Введите название организации:")
    await state.set_state(OrgRegistrationState.enter_name)


@router.message(OrgRegistrationState.enter_name)
async def register_org_name(message: Message, state: FSMContext, db_user, session):
    data = await state.get_data()
    inn = data.get("inn")
    name = message.text.strip()
    password = secrets.token_urlsafe(8)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    org = await create_org(session, inn, name, password_hash, message.from_user.id)
    await message.answer(
        f"Организация зарегистрирована. Пароль (показывается один раз): {password}"
    )
    await state.clear()


@router.message(F.text == "Статистика по обращениям")
async def support_stats(message: Message, db_user, session):
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    open_count, closed_count = await get_support_stats(session)
    await message.answer(f"Активные обращения: {open_count}\nЗакрытые обращения: {closed_count}")


@router.message(F.text == "Указание реквизитов для выплат")
async def payout_start(message: Message, state: FSMContext):
    await message.answer("Введите реквизиты для выплат:")
    await state.set_state(PayoutState.enter_details)


@router.message(PayoutState.enter_details)
async def payout_save(message: Message, state: FSMContext, db_user, session):
    details = message.text.strip()
    await update_user_payout_details(session, db_user.id, details)
    await message.answer("Реквизиты сохранены.")
    await state.clear()


@router.message(F.text == "Принудительно обновить данные из 1С")
async def manual_sync(message: Message, db_user, session, config):
    if db_user.role not in {"SUPER_ADMIN", "ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Запускаю синхронизацию...")
    last_closed = get_last_closed_month(config.timezone)
    start, end = month_range(last_closed)
    client = ErpClient(config.erp_http_url, config.erp_http_user, config.erp_http_password, config.erp_timeout_sec)
    rows = await client.fetch_sales(start, end)
    await upsert_erp_sales(session, rows)
    await message.answer("Синхронизация завершена.")
