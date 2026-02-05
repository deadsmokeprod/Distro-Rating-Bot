import json
from datetime import datetime
from typing import Iterable
from sqlalchemy import select, update, insert, func, and_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from .models import (
    AuditLog,
    Organization,
    User,
    ErpSale,
    SaleConfirmation,
    SupportTicket,
    SupportMessage,
)


async def get_user_by_tg(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, tg_id: int, role: str, full_name: str, org_id: int | None):
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


async def update_last_seen(session: AsyncSession, tg_id: int):
    await session.execute(update(User).where(User.tg_id == tg_id).values(last_seen_at=datetime.utcnow()))
    await session.commit()


async def get_org_by_inn(session: AsyncSession, inn: str) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.inn == inn))
    return result.scalar_one_or_none()


async def get_org_by_id(session: AsyncSession, org_id: int) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def create_org(session: AsyncSession, inn: str, name: str, password_hash: str, admin_tg_id: int) -> Organization:
    org = Organization(
        inn=inn,
        name=name,
        password_hash=password_hash,
        created_by_admin_tg_id=admin_tg_id,
        created_at=datetime.utcnow(),
        is_active=1,
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def log_audit(session: AsyncSession, tg_id: int | None, role: str | None, action: str, meta: dict | None = None):
    entry = AuditLog(
        tg_id=tg_id,
        role=role,
        action=action,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        created_at=datetime.utcnow(),
    )
    session.add(entry)
    await session.commit()


async def upsert_erp_sales(session: AsyncSession, rows: Iterable[dict]):
    for row in rows:
        stmt = insert(ErpSale).values(**row)
        update_cols = {
            "month_key": row["month_key"],
            "period": row["period"],
            "operation_type": row.get("operation_type"),
            "product_name": row.get("product_name"),
            "volume_total": row["volume_total"],
            "volume_partial": row.get("volume_partial"),
            "seller_inn": row["seller_inn"],
            "seller_name": row.get("seller_name"),
            "buyer_inn": row.get("buyer_inn"),
            "buyer_name": row.get("buyer_name"),
            "loaded_at": row["loaded_at"],
        }
        stmt = stmt.on_conflict_do_update(index_elements=[ErpSale.source_hash], set_=update_cols)
        await session.execute(stmt)
    await session.commit()


async def get_sales_for_org(session: AsyncSession, seller_inn: str, month_key: str, limit: int, offset: int):
    subquery = select(SaleConfirmation.sale_id)
    result = await session.execute(
        select(ErpSale)
        .where(
            and_(
                ErpSale.seller_inn == seller_inn,
                ErpSale.month_key == month_key,
                ErpSale.id.not_in(subquery),
            )
        )
        .order_by(ErpSale.id)
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def confirm_sale(session: AsyncSession, sale_id: int, user_id: int, org_id: int):
    confirmation = SaleConfirmation(
        sale_id=sale_id,
        user_id=user_id,
        org_id=org_id,
        confirmed_at=datetime.utcnow(),
    )
    session.add(confirmation)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise


async def get_orgs_by_admin(session: AsyncSession, admin_tg_id: int):
    result = await session.execute(select(Organization).where(Organization.created_by_admin_tg_id == admin_tg_id))
    return result.scalars().all()


async def get_support_ticket_by_user(session: AsyncSession, user_id: int):
    result = await session.execute(
        select(SupportTicket).where(
            and_(SupportTicket.user_id == user_id, SupportTicket.status == "OPEN")
        )
    )
    return result.scalar_one_or_none()


async def get_support_ticket_by_thread(session: AsyncSession, thread_id: int):
    result = await session.execute(select(SupportTicket).where(SupportTicket.thread_id == thread_id))
    return result.scalar_one_or_none()


async def create_support_ticket(session: AsyncSession, user_id: int, org_id: int | None, curator_admin_tg_id: int | None, subject: str, thread_id: int):
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


async def close_support_ticket(session: AsyncSession, ticket_id: int, reason: str):
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
    text_value: str | None,
    file_id: str | None,
):
    message = SupportMessage(
        ticket_id=ticket_id,
        direction=direction,
        msg_type=msg_type,
        text=text_value,
        file_id=file_id,
        created_at=datetime.utcnow(),
    )
    session.add(message)
    await session.commit()


async def get_support_stats(session: AsyncSession):
    open_count = await session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "OPEN"))
    closed_count = await session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "CLOSED"))
    return open_count or 0, closed_count or 0


async def update_user_payout_details(session: AsyncSession, user_id: int, details: str):
    await session.execute(update(User).where(User.id == user_id).values(payout_details=details))
    await session.commit()
