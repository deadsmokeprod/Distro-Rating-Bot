from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List

from sqlalchemy import and_, desc, func, insert, select, update
from sqlalchemy.exc import IntegrityError
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


async def add_audit_log(session: AsyncSession, tg_id: int | None, role: str | None, action: str, meta: dict) -> None:
    session.add(
        AuditLog(
            tg_id=tg_id,
            role=role,
            action=action,
            meta_json=json.dumps(meta, ensure_ascii=False),
        )
    )
    await session.commit()


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, tg_id: int, role: str, full_name: str, org_id: int | None) -> User:
    user = User(tg_id=tg_id, role=role, full_name=full_name, org_id=org_id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_last_seen(session: AsyncSession, tg_id: int) -> None:
    await session.execute(update(User).where(User.tg_id == tg_id).values(last_seen_at=datetime.utcnow()))
    await session.commit()


async def update_user_role(session: AsyncSession, tg_id: int, role: str) -> None:
    await session.execute(update(User).where(User.tg_id == tg_id).values(role=role))
    await session.commit()


async def update_payout_details(session: AsyncSession, user_id: int, details: str) -> None:
    await session.execute(update(User).where(User.id == user_id).values(payout_details=details))
    await session.commit()


async def get_org_by_inn(session: AsyncSession, inn: str) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.inn == inn))
    return result.scalar_one_or_none()


async def get_org_by_id(session: AsyncSession, org_id: int) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def create_organization(
    session: AsyncSession, inn: str, name: str, password_hash: str, created_by_admin_tg_id: int
) -> Organization:
    org = Organization(
        inn=inn,
        name=name,
        password_hash=password_hash,
        created_by_admin_tg_id=created_by_admin_tg_id,
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def list_orgs_created_by_admin(session: AsyncSession, admin_tg_id: int) -> List[Organization]:
    result = await session.execute(select(Organization).where(Organization.created_by_admin_tg_id == admin_tg_id))
    return list(result.scalars().all())


async def upsert_erp_sale(session: AsyncSession, data: dict) -> None:
    stmt = insert(ErpSale).values(**data)
    update_dict = {k: data[k] for k in data.keys() if k not in {"id", "source_hash"}}
    stmt = stmt.on_conflict_do_update(index_elements=[ErpSale.source_hash], set_=update_dict)
    await session.execute(stmt)


async def commit_sales(session: AsyncSession) -> None:
    await session.commit()


async def list_sales_for_confirmation(session: AsyncSession, seller_inn: str, month_key: str, limit: int, offset: int) -> List[ErpSale]:
    subquery = select(SaleConfirmation.sale_id)
    query = (
        select(ErpSale)
        .where(and_(ErpSale.seller_inn == seller_inn, ErpSale.month_key == month_key, ~ErpSale.id.in_(subquery)))
        .order_by(ErpSale.id)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def confirm_sale(session: AsyncSession, sale_id: int, user_id: int, org_id: int) -> bool:
    confirmation = SaleConfirmation(sale_id=sale_id, user_id=user_id, org_id=org_id)
    session.add(confirmation)
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def get_org_rating(session: AsyncSession, seller_inn: str, month_key: str) -> Decimal:
    result = await session.execute(
        select(func.sum(ErpSale.volume_total)).where(
            and_(ErpSale.seller_inn == seller_inn, ErpSale.month_key == month_key)
        )
    )
    value = result.scalar_one_or_none() or "0"
    return Decimal(str(value).replace(",", "."))


async def get_personal_rating(session: AsyncSession, user_id: int, month_key: str) -> Decimal:
    result = await session.execute(
        select(func.sum(ErpSale.volume_total))
        .select_from(ErpSale)
        .join(SaleConfirmation, SaleConfirmation.sale_id == ErpSale.id)
        .where(and_(SaleConfirmation.user_id == user_id, ErpSale.month_key == month_key))
    )
    value = result.scalar_one_or_none() or "0"
    return Decimal(str(value).replace(",", "."))


async def list_org_ratings(session: AsyncSession, month_key: str) -> list[tuple[str, str, Decimal]]:
    result = await session.execute(
        select(ErpSale.seller_inn, ErpSale.seller_name, func.sum(ErpSale.volume_total))
        .where(ErpSale.month_key == month_key)
        .group_by(ErpSale.seller_inn, ErpSale.seller_name)
        .order_by(desc(func.sum(ErpSale.volume_total)))
    )
    rows = []
    for inn, name, total in result.fetchall():
        rows.append((inn, name or "", Decimal(str(total or "0").replace(",", "."))))
    return rows


async def list_personal_ratings_for_org(session: AsyncSession, org_id: int, month_key: str) -> list[tuple[str, Decimal]]:
    result = await session.execute(
        select(User.full_name, func.sum(ErpSale.volume_total))
        .select_from(SaleConfirmation)
        .join(User, User.id == SaleConfirmation.user_id)
        .join(ErpSale, ErpSale.id == SaleConfirmation.sale_id)
        .where(and_(SaleConfirmation.org_id == org_id, ErpSale.month_key == month_key))
        .group_by(User.full_name)
        .order_by(desc(func.sum(ErpSale.volume_total)))
    )
    data = []
    for full_name, total in result.fetchall():
        data.append((full_name, Decimal(str(total or "0").replace(",", "."))))
    return data


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
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def get_open_ticket_by_user(session: AsyncSession, user_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket).where(and_(SupportTicket.user_id == user_id, SupportTicket.status == "OPEN"))
    )
    return result.scalar_one_or_none()


async def get_ticket_by_thread(session: AsyncSession, thread_id: int) -> SupportTicket | None:
    result = await session.execute(select(SupportTicket).where(SupportTicket.thread_id == thread_id))
    return result.scalar_one_or_none()


async def close_ticket(session: AsyncSession, ticket_id: int, reason: str) -> None:
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
    session.add(
        SupportMessage(
            ticket_id=ticket_id,
            direction=direction,
            msg_type=msg_type,
            text=text,
            file_id=file_id,
        )
    )
    await session.commit()


async def get_ticket_stats(session: AsyncSession) -> tuple[int, int]:
    active_result = await session.execute(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "OPEN"))
    closed_result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "CLOSED")
    )
    return int(active_result.scalar_one()), int(closed_result.scalar_one())
