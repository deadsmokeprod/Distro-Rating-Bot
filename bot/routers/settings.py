import secrets

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import load_config
from bot.db.repo import create_organization, get_org_by_inn, get_ticket_stats, update_user_requisites
from bot.keyboards.menu import settings_menu
from bot.services.erp_sync import sync_from_erp
from bot.services.security import hash_password


router = Router()


class OrgRegistrationStates(StatesGroup):
    entering_inn = State()
    entering_name = State()


@router.message(lambda message: message.text == "Настройки (админская панель)")
async def settings_root(message: Message, user):
    await message.answer("Выберите действие:", reply_markup=settings_menu(user.role))


@router.message(lambda message: message.text == "Регистрация дистрибьютера")
async def register_distributor(message: Message, state: FSMContext, user):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Введите ИНН:")
    await state.set_state(OrgRegistrationStates.entering_inn)


@router.message(OrgRegistrationStates.entering_inn)
async def register_distributor_inn(message: Message, state: FSMContext):
    await state.update_data(inn=message.text.strip())
    await message.answer("Введите наименование организации:")
    await state.set_state(OrgRegistrationStates.entering_name)


@router.message(OrgRegistrationStates.entering_name)
async def register_distributor_name(
    message: Message, state: FSMContext, session: AsyncSession, user
):
    data = await state.get_data()
    existing = await get_org_by_inn(session, data["inn"])
    if existing:
        await message.answer("Организация с таким ИНН уже зарегистрирована.")
        await state.clear()
        return
    password_plain = secrets.token_urlsafe(8)
    password_hash = hash_password(password_plain)
    await create_organization(
        session,
        inn=data["inn"],
        name=message.text.strip(),
        password_hash=password_hash,
        created_by_admin_tg_id=user.tg_id,
    )
    await message.answer(
        "Организация зарегистрирована. Пароль (показан один раз): "
        f"{password_plain}"
    )
    await state.clear()


@router.message(lambda message: message.text == "Статистика по обращениям")
async def support_stats(message: Message, session: AsyncSession, user):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    stats = await get_ticket_stats(session)
    await message.answer(
        f"Активные обращения: {stats['open']}\nЗакрытые обращения: {stats['closed']}"
    )


@router.message(lambda message: message.text == "Указание реквизитов для выплат")
async def set_requisites(message: Message, state: FSMContext):
    await message.answer("Введите реквизиты для выплат:")
    await state.set_state("requisites")


@router.message(lambda message: message.text == "Принудительно обновить данные из 1С")
async def force_sync(message: Message, session: AsyncSession, user):
    if user.role not in {"ADMIN", "SUPER_ADMIN"}:
        await message.answer("Недостаточно прав.")
        return
    config = load_config()
    count = await sync_from_erp(session, config.timezone)
    await message.answer(f"Синхронизация завершена. Обработано записей: {count}.")


@router.message(state="requisites")
async def save_requisites(message: Message, state: FSMContext, session: AsyncSession, user):
    await update_user_requisites(session, user.id, message.text.strip())
    await message.answer("Реквизиты сохранены.")
    await state.clear()
