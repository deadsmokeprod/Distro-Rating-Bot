import json
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import select, update, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    AuditLog,
    ErpSale,
    Organization,
    SaleConfirmation,
    SupportMessage,
    SupportTicket,
    User,
)


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_org_by_inn(session: AsyncSession, inn: str) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.inn == inn))
    return result.scalar_one_or_none()


async def get_org_by_id(session: AsyncSession, org_id: int) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    tg_id: int,
    role: str,
    full_name: str,
    org_id: int | None,
) -> User:
    user = User(
        tg_id=tg_id,
        role=role,
        full_name=full_name,
        org_id=org_id,
        registered_at=datetime.utcnow(),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def create_organization(
    session: AsyncSession,
    inn: str,
    name: str,
    password_hash: str,
    created_by_admin_tg_id: int,
) -> Organization:
    org = Organization(
        inn=inn,
        name=name,
        password_hash=password_hash,
        created_by_admin_tg_id=created_by_admin_tg_id,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def log_audit(
    session: AsyncSession,
    tg_id: int | None,
    role: str | None,
    action: str,
    meta: dict | None = None,
) -> None:
    entry = AuditLog(
        tg_id=tg_id,
        role=role,
        action=action,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        created_at=datetime.utcnow(),
    )
    session.add(entry)
    await session.commit()


async def upsert_sales(session: AsyncSession, sales: Iterable[dict]) -> int:
    count = 0
    for sale in sales:
        stmt = insert(ErpSale).values(**sale)
        update_cols = {k: stmt.excluded[k] for k in sale.keys() if k != "source_hash"}
        stmt = stmt.on_conflict_do_update(index_elements=[ErpSale.source_hash], set_=update_cols)
        await session.execute(stmt)
        count += 1
    await session.commit()
    return count


async def get_unconfirmed_sales(
    session: AsyncSession,
    seller_inn: str,
    month_key: str,
    limit: int = 10,
) -> Sequence[ErpSale]:
    subq = select(SaleConfirmation.sale_id)
    result = await session.execute(
        select(ErpSale)
        .where(ErpSale.seller_inn == seller_inn)
        .where(ErpSale.month_key == month_key)
        .where(~ErpSale.id.in_(subq))
        .limit(limit)
    )
    return result.scalars().all()


async def confirm_sale(
    session: AsyncSession,
    sale_id: int,
    user_id: int,
    org_id: int,
) -> None:
    confirmation = SaleConfirmation(
        sale_id=sale_id,
        user_id=user_id,
        org_id=org_id,
        confirmed_at=datetime.utcnow(),
    )
    session.add(confirmation)
    await session.commit()


async def get_support_ticket_by_user(session: AsyncSession, user_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.user_id == user_id, SupportTicket.status == "OPEN"
        )
    )
    return result.scalar_one_or_none()


async def get_support_ticket_by_thread(session: AsyncSession, thread_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.thread_id == thread_id)
    )
    return result.scalar_one_or_none()


async def create_support_ticket(
    session: AsyncSession,
    user_id: int,
    org_id: int | None,
    curator_admin_tg_id: int | None,
    subject: str,
    thread_id: int,
) -> SupportTicket:
    ticket = SupportTicket(
        user_id=user_id,
        org_id=org_id,
        curator_admin_tg_id=curator_admin_tg_id,
        subject=subject,
        status="OPEN",
        thread_id=thread_id,
        created_at=datetime.utcnow(),
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def close_support_ticket(
    session: AsyncSession,
    ticket_id: int,
    reason: str,
) -> None:
    await session.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .values(status="CLOSED", closed_at=datetime.utcnow(), close_reason=reason)
    )
    await session.commit()


async def add_support_message(
    session: AsyncSession,
    ticket_id: int,
    direction: str,
    msg_type: str,
    text: str | None,
    file_id: str | None,
) -> None:
    message = SupportMessage(
        ticket_id=ticket_id,
        direction=direction,
        msg_type=msg_type,
        text=text,
        file_id=file_id,
        created_at=datetime.utcnow(),
    )
    session.add(message)
    await session.commit()


async def get_ticket_stats(session: AsyncSession) -> dict:
    open_count = await session.scalar(
        select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "OPEN")
    )
    closed_count = await session.scalar(
        select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "CLOSED")
    )
    return {"open": open_count or 0, "closed": closed_count or 0}


async def update_user_requisites(session: AsyncSession, user_id: int, requisites: str) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(payout_requisites=requisites)
    )
    await session.commit()


async def update_last_seen(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(last_seen_at=datetime.utcnow())
    )
    await session.commit()
