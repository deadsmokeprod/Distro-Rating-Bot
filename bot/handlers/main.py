from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable

import bcrypt
import pytz
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..db import Database
from ..keyboards import BACK_BUTTON_TEXT, make_keyboard
from ..models import ErpSale, Organization, SaleConfirmation, SupportTicket, User
from ..services.erp import sync_erp_sales
from ..services.rating import get_world_rating
from ..services.support import get_open_ticket, get_open_ticket_by_topic

logger = logging.getLogger(__name__)

ROLE_SELLER = "SELLER"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"

BTN_WORLD_RATING = "🌍 Мировой рейтинг"
BTN_CONFIRM_SALE = "✅ Подтвердить продажу"
BTN_PROFILE = "👤 Профиль"
BTN_SUPPORT = "🆘 Поддержка"
BTN_SETTINGS = "⚙️ Настройки"

BTN_SHOW_UNCONFIRMED = "📋 Показать неподтверждённые"
BTN_CONFIRM_BY_NUMBER = "🔎 Подтвердить по номеру"

BTN_EDIT_NAME = "✏️ Изменить имя"

BTN_SUPPORT_CREATE = "✉️ Создать обращение"
BTN_SUPPORT_CLOSE = "⛔ Закрыть обращение"

BTN_SYNC_NOW = "🔄 Запустить синхронизацию сейчас"
BTN_ORGS = "🏢 Организации"

BTN_ORG_ADD = "➕ Добавить организацию"
BTN_ORG_LIST = "📄 Список организаций"


class RegistrationStates(StatesGroup):
    waiting_name = State()
    waiting_org_code = State()


class ProfileStates(StatesGroup):
    waiting_new_name = State()


class SalesStates(StatesGroup):
    waiting_sale_id = State()


class OrgStates(StatesGroup):
    waiting_inn = State()
    waiting_name = State()
    waiting_code = State()


router = Router()


def main_menu(role: str) -> Iterable[str]:
    base = [BTN_WORLD_RATING, BTN_CONFIRM_SALE, BTN_PROFILE, BTN_SUPPORT]
    if role == ROLE_SUPER_ADMIN:
        base.append(BTN_SETTINGS)
    return base


def profile_menu() -> Iterable[str]:
    return [BTN_EDIT_NAME, BACK_BUTTON_TEXT]


def sales_menu() -> Iterable[str]:
    return [BTN_SHOW_UNCONFIRMED, BTN_CONFIRM_BY_NUMBER, BACK_BUTTON_TEXT]


def support_menu() -> Iterable[str]:
    return [BTN_SUPPORT_CREATE, BTN_SUPPORT_CLOSE, BACK_BUTTON_TEXT]


def settings_menu() -> Iterable[str]:
    return [BTN_SYNC_NOW, BTN_ORGS, BACK_BUTTON_TEXT]


def org_menu() -> Iterable[str]:
    return [BTN_ORG_ADD, BTN_ORG_LIST, BACK_BUTTON_TEXT]


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def get_role(session: AsyncSession, tg_id: int) -> str | None:
    user = await get_user(session, tg_id)
    return user.role if user else None


async def send_main_menu(message: Message, role: str) -> None:
    await message.answer("Главное меню:", reply_markup=make_keyboard(list(main_menu(role))))


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
    if user:
        await state.clear()
        await send_main_menu(message, user.role)
        return
    await state.set_state(RegistrationStates.waiting_name)
    await message.answer("Введите ваше имя (2-64 символа):", reply_markup=make_keyboard([BACK_BUTTON_TEXT]))


@router.message(F.text == BACK_BUTTON_TEXT)
async def back_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
    if user:
        await send_main_menu(message, user.role)
    else:
        await message.answer("Введите /start для начала регистрации.")


@router.message(RegistrationStates.waiting_name)
async def registration_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 64:
        await message.answer("Имя должно быть от 2 до 64 символов. Попробуйте ещё раз.")
        return
    await state.update_data(full_name=text)
    await state.set_state(RegistrationStates.waiting_org_code)
    await message.answer(
        "Введите код организации:",
        reply_markup=make_keyboard([BACK_BUTTON_TEXT]),
    )


@router.message(RegistrationStates.waiting_org_code)
async def registration_org_code(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer("Введите /start для начала регистрации.")
        return
    db: Database = message.bot["db"]
    config: Config = message.bot["config"]
    async with db.session()() as session:
        orgs = await session.scalars(select(Organization))
        matched = None
        for org in orgs:
            if bcrypt.checkpw(text.encode("utf-8"), org.access_hash.encode("utf-8")):
                matched = org
                break
        if not matched:
            await message.answer(
                "Код неверный, попробуйте ещё раз.",
                reply_markup=make_keyboard([BACK_BUTTON_TEXT]),
            )
            return
        data = await state.get_data()
        full_name = data.get("full_name")
        role = ROLE_SUPER_ADMIN if message.from_user.id in config.super_admin_ids else ROLE_SELLER
        session.add(
            User(
                tg_id=message.from_user.id,
                full_name=full_name,
                role=role,
                organization_inn=matched.inn,
            )
        )
        await session.commit()
    await state.clear()
    await send_main_menu(message, role)


@router.message(F.text == BTN_PROFILE)
async def profile_handler(message: Message) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start.")
            return
        org = await session.scalar(select(Organization).where(Organization.inn == user.organization_inn))
    text = (
        f"Имя: {user.full_name}\n"
        f"Роль: {user.role}\n"
        f"Организация: {org.name if org else '—'} ({user.organization_inn})"
    )
    await message.answer(text, reply_markup=make_keyboard(list(profile_menu())))


@router.message(F.text == BTN_EDIT_NAME)
async def edit_name_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileStates.waiting_new_name)
    await message.answer("Введите новое имя:", reply_markup=make_keyboard([BACK_BUTTON_TEXT]))


@router.message(ProfileStates.waiting_new_name)
async def edit_name_save(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 64:
        await message.answer("Имя должно быть от 2 до 64 символов. Попробуйте ещё раз.")
        return
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start.")
            await state.clear()
            return
        user.full_name = text
        await session.commit()
    await state.clear()
    await message.answer("Имя обновлено.")
    await profile_handler(message)


@router.message(F.text == BTN_CONFIRM_SALE)
async def confirm_sale_menu(message: Message) -> None:
    await message.answer("Подтверждение продаж:", reply_markup=make_keyboard(list(sales_menu())))


@router.message(F.text == BTN_SHOW_UNCONFIRMED)
async def show_unconfirmed(message: Message) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start.")
            return
        stmt = (
            select(ErpSale)
            .outerjoin(SaleConfirmation, SaleConfirmation.sale_id == ErpSale.id)
            .where(
                and_(
                    ErpSale.seller_inn == user.organization_inn,
                    SaleConfirmation.id.is_(None),
                )
            )
            .order_by(ErpSale.doc_date.desc())
            .limit(10)
        )
        sales = (await session.scalars(stmt)).all()
    if not sales:
        await message.answer("Нет неподтверждённых продаж.")
        return
    lines = []
    for sale in sales:
        date_str = sale.doc_date.strftime("%Y-%m-%d")
        buyer = sale.buyer_name or "—"
        lines.append(f"{sale.id} | {date_str} | {buyer} | {sale.volume_total_l:.2f} л")
    await message.answer("\n".join(lines))


@router.message(F.text == BTN_CONFIRM_BY_NUMBER)
async def confirm_by_number_start(message: Message, state: FSMContext) -> None:
    await state.set_state(SalesStates.waiting_sale_id)
    await message.answer("Введите номер продажи (sale_id):", reply_markup=make_keyboard([BACK_BUTTON_TEXT]))


@router.message(SalesStates.waiting_sale_id)
async def confirm_by_number_save(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await confirm_sale_menu(message)
        return
    if not text.isdigit():
        await message.answer("Номер должен быть целым числом. Попробуйте ещё раз.")
        return
    sale_id = int(text)
    db: Database = message.bot["db"]
    async with db.session()() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start.")
            await state.clear()
            return
        sale = await session.get(ErpSale, sale_id)
        if not sale:
            await message.answer("Не найдено. Проверь номер.")
            return
        if sale.seller_inn != user.organization_inn:
            await message.answer("Эта продажа относится к другой организации.")
            return
        existing = await session.scalar(select(SaleConfirmation).where(SaleConfirmation.sale_id == sale_id))
        if existing:
            await message.answer("Эта продажа уже подтверждена.")
            return
        session.add(SaleConfirmation(sale_id=sale_id, tg_id=user.tg_id))
        try:
            await session.commit()
        except Exception:
            logger.exception("Failed to confirm sale")
            await session.rollback()
            await message.answer("Внутренняя ошибка БД. Попробуйте позже.")
            return
    await state.clear()
    await message.answer("✅ Продажа подтверждена и учтена в рейтинге.")


@router.message(F.text == BTN_WORLD_RATING)
async def world_rating_handler(message: Message) -> None:
    config: Config = message.bot["config"]
    tz = pytz.timezone(config.timezone)
    now = dt.datetime.now(tz)
    month_start = now.replace(day=1).date()
    if month_start.month == 12:
        next_month = dt.date(month_start.year + 1, 1, 1)
    else:
        next_month = dt.date(month_start.year, month_start.month + 1, 1)
    month_end = next_month - dt.timedelta(days=1)
    db: Database = message.bot["db"]
    async with db.session()() as session:
        rating = await get_world_rating(session, month_start, month_end)
    month_label = month_start.strftime("%Y-%m")
    if not rating:
        await message.answer(f"Пока нет подтверждённых продаж для рейтинга за {month_label}.")
        return
    lines = [f"🌍 Мировой рейтинг продавцов — {month_label}"]
    for idx, (name, total) in enumerate(rating, start=1):
        lines.append(f"{idx}) {name} — {total:.2f} л")
    await message.answer("\n".join(lines))


@router.message(F.text == BTN_SUPPORT)
async def support_handler(message: Message) -> None:
    config: Config = message.bot["config"]
    if not config.bot_support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    await message.answer("Поддержка:", reply_markup=make_keyboard(list(support_menu())))


@router.message(F.text == BTN_SUPPORT_CREATE)
async def support_create(message: Message) -> None:
    config: Config = message.bot["config"]
    if not config.bot_support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    db: Database = message.bot["db"]
    async with db.session()() as session:
        ticket = await get_open_ticket(session, message.from_user.id)
        if ticket:
            await message.answer("У вас уже есть открытое обращение.")
            return
        title = f"{message.from_user.full_name} | {message.from_user.id}"
        try:
            topic = await message.bot.create_forum_topic(config.bot_support_group_id, title)
        except Exception:
            logger.exception("Failed to create support topic")
            await message.answer("Не удалось создать обращение. Попробуйте позже.")
            return
        session.add(
            SupportTicket(
                tg_id=message.from_user.id,
                topic_id=topic.message_thread_id,
                status="open",
            )
        )
        await session.commit()
    await message.answer("Обращение создано. Опишите проблему одним сообщением или несколькими.")


@router.message(F.text == BTN_SUPPORT_CLOSE)
async def support_close(message: Message) -> None:
    config: Config = message.bot["config"]
    if not config.bot_support_group_id:
        await message.answer("Поддержка не настроена. Сообщите администратору.")
        return
    db: Database = message.bot["db"]
    async with db.session()() as session:
        ticket = await get_open_ticket(session, message.from_user.id)
        if not ticket:
            await message.answer("Открытых обращений нет.")
            return
        ticket.status = "closed"
        ticket.closed_at = dt.datetime.utcnow()
        await session.commit()
    await message.answer("Обращение закрыто.")


@router.message(F.text == BTN_SETTINGS)
async def settings_handler(message: Message) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        role = await get_role(session, message.from_user.id)
    if role != ROLE_SUPER_ADMIN:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Настройки:", reply_markup=make_keyboard(list(settings_menu())))


@router.message(F.text == BTN_SYNC_NOW)
async def sync_now_handler(message: Message) -> None:
    config: Config = message.bot["config"]
    db: Database = message.bot["db"]
    async with db.session()() as session:
        role = await get_role(session, message.from_user.id)
        if role != ROLE_SUPER_ADMIN:
            await message.answer("Недостаточно прав.")
            return
        added, updated = await sync_erp_sales(session, config.erp_url, config.erp_username, config.erp_password)
        await session.commit()
    await message.answer(f"✅ Синхронизация завершена: добавлено {added}, обновлено {updated}.")


@router.message(F.text == BTN_ORGS)
async def orgs_menu_handler(message: Message) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        role = await get_role(session, message.from_user.id)
    if role != ROLE_SUPER_ADMIN:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Организации:", reply_markup=make_keyboard(list(org_menu())))


@router.message(F.text == BTN_ORG_ADD)
async def org_add_start(message: Message, state: FSMContext) -> None:
    await state.set_state(OrgStates.waiting_inn)
    await message.answer("Введите ИНН (10 или 12 цифр):", reply_markup=make_keyboard([BACK_BUTTON_TEXT]))


@router.message(OrgStates.waiting_inn)
async def org_add_inn(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await orgs_menu_handler(message)
        return
    if not text.isdigit() or len(text) not in (10, 12):
        await message.answer("ИНН должен быть 10 или 12 цифр.")
        return
    await state.update_data(inn=text)
    await state.set_state(OrgStates.waiting_name)
    await message.answer("Введите название организации:")


@router.message(OrgStates.waiting_name)
async def org_add_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Название слишком короткое. Попробуйте ещё раз.")
        return
    await state.update_data(name=text)
    await state.set_state(OrgStates.waiting_code)
    await message.answer("Введите код доступа (пароль):")


@router.message(OrgStates.waiting_code)
async def org_add_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    if len(code) < 4:
        await message.answer("Код доступа слишком короткий. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    inn = data.get("inn")
    name = data.get("name")
    db: Database = message.bot["db"]
    async with db.session()() as session:
        existing = await session.get(Organization, inn)
        if existing:
            await message.answer("Организация с таким ИНН уже создана.")
            await state.clear()
            return
        access_hash = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        session.add(Organization(inn=inn, name=name, access_hash=access_hash))
        try:
            await session.commit()
        except Exception:
            logger.exception("Failed to add organization")
            await session.rollback()
            await message.answer("Не удалось сохранить организацию. Попробуйте позже.")
            return
    await state.clear()
    await message.answer("Организация добавлена.")


@router.message(F.text == BTN_ORG_LIST)
async def org_list(message: Message) -> None:
    db: Database = message.bot["db"]
    async with db.session()() as session:
        orgs = (await session.scalars(select(Organization).order_by(Organization.name))).all()
    if not orgs:
        await message.answer("Организаций нет.")
        return
    lines = [f"{org.inn} — {org.name}" for org in orgs]
    await message.answer("\n".join(lines))


@router.message(F.chat.type == ChatType.PRIVATE)
async def forward_user_messages(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    if await state.get_state() is not None:
        return
    config: Config = message.bot["config"]
    if not config.bot_support_group_id:
        return
    db: Database = message.bot["db"]
    async with db.session()() as session:
        ticket = await get_open_ticket(session, message.from_user.id)
    if not ticket:
        return
    try:
        await message.bot.copy_message(
            chat_id=config.bot_support_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=ticket.topic_id,
        )
    except Exception:
        logger.exception("Failed to forward message to support")
        await message.answer("Не удалось отправить сообщение в поддержку. Попробуйте позже.")


@router.message(F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}))
async def forward_support_messages(message: Message) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    config: Config = message.bot["config"]
    if not config.bot_support_group_id or message.chat.id != config.bot_support_group_id:
        return
    if not message.message_thread_id:
        return
    db: Database = message.bot["db"]
    async with db.session()() as session:
        ticket = await get_open_ticket_by_topic(session, message.message_thread_id)
    if not ticket:
        return
    try:
        await message.bot.copy_message(
            chat_id=ticket.tg_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("Failed to forward support reply")


@router.message()
async def fallback_handler(message: Message) -> None:
    await message.answer("Неизвестная команда. Используйте /start или кнопки меню.")
