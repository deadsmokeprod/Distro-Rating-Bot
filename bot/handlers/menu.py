from __future__ import annotations

import datetime as dt
import logging

import bcrypt
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..keyboards import (
    BACK_TEXT,
    back_only,
    confirm_menu,
    main_menu,
    organizations_menu,
    profile_menu,
    settings_menu,
    support_menu,
)
from ..models import ErpSale, Organization, SaleConfirmation, SupportTicket, User
from ..services.erp_sync import sync_sales
from ..services.rating import world_rating
from ..services.support import close_ticket, create_ticket, get_open_ticket
from ..states import ConfirmStates, OrganizationStates, ProfileStates
from ..utils import month_range

logger = logging.getLogger(__name__)

router = Router()


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def _show_main_menu(message: Message, user: User) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu(user.role == "SUPER_ADMIN"))


@router.message(F.text == BACK_TEXT)
async def handle_back(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if user:
        await _show_main_menu(message, user)


@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        return
    await message.answer(
        f"Имя: {user.full_name}\nРоль: {user.role}\nОрганизация: {user.organization.name} ({user.organization.inn})",
        reply_markup=profile_menu(),
    )


@router.message(F.text == "✏️ Изменить имя")
async def change_name_prompt(message: Message, state: FSMContext) -> None:
    await message.answer("Введите новое имя (2-64 символа):", reply_markup=profile_menu())
    await state.set_state(ProfileStates.rename)


@router.message(ProfileStates.rename, F.text == BACK_TEXT)
async def change_name_back(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await show_profile(message, session)


@router.message(ProfileStates.rename)
async def change_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 64:
        await message.answer("Имя должно быть от 2 до 64 символов.")
        return
    try:
        user = await _get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start.")
            await state.clear()
            return
        user.full_name = name
        await session.commit()
        await state.clear()
        await show_profile(message, session)
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Failed to update name")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "✅ Подтвердить продажу")
async def confirm_menu_show(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        return
    await message.answer("Выберите действие:", reply_markup=confirm_menu())


@router.message(F.text == "📋 Показать неподтверждённые")
async def show_unconfirmed(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        return
    try:
        stmt = (
            select(ErpSale)
            .outerjoin(SaleConfirmation, SaleConfirmation.sale_id == ErpSale.id)
            .where(ErpSale.seller_inn == user.organization_inn)
            .where(SaleConfirmation.id.is_(None))
            .order_by(ErpSale.doc_date.desc())
            .limit(10)
        )
        result = await session.execute(stmt)
        sales = result.scalars().all()
        if not sales:
            await message.answer("Нет неподтверждённых продаж.", reply_markup=confirm_menu())
            return
        lines = [
            f"{sale.id} | {sale.doc_date} | {sale.buyer_name or 'Без покупателя'} | {sale.volume_total_l} л"
            for sale in sales
        ]
        await message.answer("\n".join(lines), reply_markup=confirm_menu())
    except SQLAlchemyError:
        logger.exception("Failed to fetch unconfirmed sales")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "🔎 Подтвердить по номеру")
async def confirm_by_number_prompt(message: Message, state: FSMContext) -> None:
    await message.answer("Введите номер продажи (sale_id):", reply_markup=confirm_menu())
    await state.set_state(ConfirmStates.sale_id)


@router.message(ConfirmStates.sale_id, F.text == BACK_TEXT)
async def confirm_by_number_back(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await confirm_menu_show(message, session)


@router.message(ConfirmStates.sale_id)
async def confirm_by_number(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите корректный номер продажи.")
        return
    sale_id = int(text)
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        await state.clear()
        return
    try:
        sale = await session.get(ErpSale, sale_id)
        if not sale:
            await message.answer("Не найдено. Проверь номер.")
            return
        if sale.seller_inn != user.organization_inn:
            await message.answer("Эта продажа относится к другой организации.")
            return
        existing = await session.execute(select(SaleConfirmation).where(SaleConfirmation.sale_id == sale_id))
        if existing.scalar_one_or_none():
            await message.answer("Эта продажа уже подтверждена.")
            return
        confirmation = SaleConfirmation(sale_id=sale_id, tg_id=user.tg_id)
        session.add(confirmation)
        await session.commit()
        await message.answer("✅ Продажа подтверждена и учтена в рейтинге.")
        await state.clear()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Failed to confirm sale")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "🌍 Мировой рейтинг")
async def show_world_rating(message: Message, session: AsyncSession, config: Config) -> None:
    start_date, end_date, label = month_range(config.timezone)
    try:
        rows = await world_rating(session, start_date, end_date)
        if not rows:
            await message.answer(f"Пока нет подтверждённых продаж для рейтинга за {label}.")
            return
        lines = [f"🌍 Мировой рейтинг продавцов — {label}"]
        for idx, (name, total) in enumerate(rows, start=1):
            lines.append(f"{idx}) {name} — {round(total or 0, 2)} л")
        await message.answer("\n".join(lines))
    except SQLAlchemyError:
        logger.exception("Failed to build rating")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        return
    if user.role != "SUPER_ADMIN":
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Настройки:", reply_markup=settings_menu())


@router.message(F.text == "🔄 Запустить синхронизацию сейчас")
async def run_sync(message: Message, session: AsyncSession, config: Config) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user or user.role != "SUPER_ADMIN":
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Запущена синхронизация...")
    try:
        added, updated = await sync_sales(session, config.erp_url, config.erp_username, config.erp_password)
        await message.answer(f"✅ Синхронизация завершена: добавлено {added}, обновлено {updated}.")
    except Exception:
        logger.exception("ERP sync failed")
        await message.answer("Ошибка синхронизации. Попробуйте позже.")


@router.message(F.text == "🏢 Организации")
async def organizations(message: Message, session: AsyncSession) -> None:
    user = await _get_user(session, message.from_user.id)
    if not user or user.role != "SUPER_ADMIN":
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Организации:", reply_markup=organizations_menu())


@router.message(F.text == "➕ Добавить организацию")
async def add_org_prompt(message: Message, state: FSMContext) -> None:
    await message.answer("Введите ИНН (10 или 12 цифр):", reply_markup=back_only())
    await state.set_state(OrganizationStates.inn)


@router.message(OrganizationStates.inn, F.text == BACK_TEXT)
async def add_org_back_from_inn(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Организации:", reply_markup=organizations_menu())


@router.message(OrganizationStates.inn)
async def add_org_inn(message: Message, state: FSMContext, session: AsyncSession) -> None:
    inn = (message.text or "").strip()
    if not (inn.isdigit() and len(inn) in (10, 12)):
        await message.answer("ИНН должен быть 10 или 12 цифр.")
        return
    try:
        exists = await session.get(Organization, inn)
        if exists:
            await message.answer("Организация с таким ИНН уже создана.")
            return
        await state.update_data(inn=inn)
        await message.answer("Введите название организации:", reply_markup=back_only())
        await state.set_state(OrganizationStates.name)
    except SQLAlchemyError:
        logger.exception("Failed to validate org")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(OrganizationStates.name, F.text == BACK_TEXT)
async def add_org_back_from_name(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Организации:", reply_markup=organizations_menu())


@router.message(OrganizationStates.name)
async def add_org_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название слишком короткое.")
        return
    await state.update_data(name=name)
    await message.answer("Введите код доступа:", reply_markup=back_only())
    await state.set_state(OrganizationStates.code)


@router.message(OrganizationStates.code, F.text == BACK_TEXT)
async def add_org_back_from_code(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Организации:", reply_markup=organizations_menu())


@router.message(OrganizationStates.code)
async def add_org_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    code = (message.text or "").strip()
    if len(code) < 4:
        await message.answer("Код должен быть не короче 4 символов.")
        return
    data = await state.get_data()
    try:
        hashed = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        org = Organization(inn=data["inn"], name=data["name"], access_hash=hashed)
        session.add(org)
        await session.commit()
        await state.clear()
        await message.answer("Организация добавлена.", reply_markup=organizations_menu())
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Failed to add organization")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "📄 Список организаций")
async def list_orgs(message: Message, session: AsyncSession) -> None:
    try:
        result = await session.execute(select(Organization))
        orgs = result.scalars().all()
        if not orgs:
            await message.answer("Список организаций пуст.")
            return
        lines = [f"{org.inn} — {org.name}" for org in orgs]
        await message.answer("\n".join(lines))
    except SQLAlchemyError:
        logger.exception("Failed to list organizations")
        await message.answer("Внутренняя ошибка БД. Попробуйте позже.")


@router.message(F.text == "🆘 Поддержка")
async def support_menu_show(message: Message, config: Config) -> None:
    if not config.support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    await message.answer("Поддержка:", reply_markup=support_menu())


@router.message(F.text == "✉️ Создать обращение")
async def support_create(message: Message, session: AsyncSession, config: Config) -> None:
    if not config.support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start.")
        return
    try:
        ticket = await get_open_ticket(session, user.tg_id)
        if ticket:
            await message.answer("У вас уже есть открытое обращение.", reply_markup=support_menu())
            return
        topic = await message.bot.create_forum_topic(
            chat_id=config.support_group_id,
            name=f"{user.full_name} | {user.tg_id}",
        )
        await create_ticket(session, user.tg_id, topic.message_thread_id)
        await message.answer("Обращение создано. Опишите проблему одним сообщением или несколькими.")
    except Exception:
        logger.exception("Failed to create support ticket")
        await message.answer("Не удалось создать обращение. Попробуйте позже.")


@router.message(F.text == "⛔ Закрыть обращение")
async def support_close(message: Message, session: AsyncSession, config: Config) -> None:
    if not config.support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    try:
        closed = await close_ticket(session, message.from_user.id)
        if not closed:
            await message.answer("Открытых обращений нет.")
            return
        await message.answer("Обращение закрыто.")
    except SQLAlchemyError:
        logger.exception("Failed to close support ticket")
        await message.answer("Не удалось закрыть обращение. Попробуйте позже.")


@router.message()
async def relay_support_messages(message: Message, session: AsyncSession, config: Config) -> None:
    if not config.support_group_id:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if message.chat.id == config.support_group_id:
        if not message.message_thread_id:
            return
        result = await session.execute(
            select(SupportTicket).where(
                SupportTicket.topic_id == message.message_thread_id,
                SupportTicket.status == "open",
            )
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            return
        try:
            await message.bot.send_message(chat_id=ticket.tg_id, text=message.text or "")
        except Exception:
            logger.exception("Failed to forward support response to user")
        return
    ticket = await get_open_ticket(session, message.from_user.id)
    if ticket and message.text:
        try:
            await message.bot.send_message(
                chat_id=config.support_group_id,
                message_thread_id=ticket.topic_id,
                text=f"{message.from_user.full_name}: {message.text}",
            )
        except Exception:
            logger.exception("Failed to forward user message to support")
