import json
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import select, text, update
from sqlalchemy.orm import selectinload
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


async def get_user_by_tg(session: AsyncSession, tg_id: int) -> Optional[User]:
    result = await session.execute(
        select(User).options(selectinload(User.organization)).where(User.tg_id == tg_id)
    )
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession, tg_id: int, role: str, full_name: str, org_id: Optional[int]
) -> User:
    user = User(tg_id=tg_id, role=role, full_name=full_name, org_id=org_id)
    session.add(user)
    await session.commit()
    return user


async def update_last_seen(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(User).where(User.id == user.id).values(last_seen_at=datetime.utcnow())
    )
    await session.commit()


async def set_payout_details(session: AsyncSession, user_id: int, text_value: str) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(payout_details=text_value)
    )
    await session.commit()


async def get_organization_by_inn(session: AsyncSession, inn: str) -> Optional[Organization]:
    result = await session.execute(select(Organization).where(Organization.inn == inn))
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
    return org


async def log_audit(
    session: AsyncSession,
    tg_id: Optional[int],
    role: Optional[str],
    action: str,
    meta: Optional[dict] = None,
) -> None:
    entry = AuditLog(
        tg_id=tg_id,
        role=role,
        action=action,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
    )
    session.add(entry)
    await session.commit()


async def list_admin_organizations(session: AsyncSession, tg_id: int) -> List[Organization]:
    result = await session.execute(
        select(Organization).where(Organization.created_by_admin_tg_id == tg_id)
    )
    return list(result.scalars().all())


async def upsert_erp_sales(session: AsyncSession, rows: Iterable[dict]) -> int:
    inserted = 0
    for row in rows:
        stmt = text(
            """
            INSERT INTO erp_sales (
                source_hash, month_key, period, operation_type, product_name,
                volume_total, volume_partial, seller_inn, seller_name,
                buyer_inn, buyer_name, loaded_at
            ) VALUES (
                :source_hash, :month_key, :period, :operation_type, :product_name,
                :volume_total, :volume_partial, :seller_inn, :seller_name,
                :buyer_inn, :buyer_name, :loaded_at
            )
            ON CONFLICT(source_hash) DO UPDATE SET
                month_key=excluded.month_key,
                period=excluded.period,
                operation_type=excluded.operation_type,
                product_name=excluded.product_name,
                volume_total=excluded.volume_total,
                volume_partial=excluded.volume_partial,
                seller_inn=excluded.seller_inn,
                seller_name=excluded.seller_name,
                buyer_inn=excluded.buyer_inn,
                buyer_name=excluded.buyer_name,
                loaded_at=excluded.loaded_at
            """
        )
        await session.execute(stmt, row)
        inserted += 1
    await session.commit()
    return inserted


async def list_unconfirmed_sales(
    session: AsyncSession, seller_inn: str, month_key: str, limit: int, offset: int
) -> List[ErpSale]:
    result = await session.execute(
        text(
            """
            SELECT * FROM erp_sales
            WHERE seller_inn = :seller_inn
              AND month_key = :month_key
              AND id NOT IN (SELECT sale_id FROM sale_confirmations)
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        ),
        {"seller_inn": seller_inn, "month_key": month_key, "limit": limit, "offset": offset},
    )
    return [ErpSale(**row._mapping) for row in result]


async def confirm_sale(
    session: AsyncSession, sale_id: int, user_id: int, org_id: int
) -> bool:
    try:
        stmt = text(
            """
            INSERT INTO sale_confirmations (sale_id, user_id, org_id, confirmed_at)
            VALUES (:sale_id, :user_id, :org_id, :confirmed_at)
            """
        )
        await session.execute(
            stmt,
            {
                "sale_id": sale_id,
                "user_id": user_id,
                "org_id": org_id,
                "confirmed_at": datetime.utcnow(),
            },
        )
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        return False


async def get_sale_by_id(session: AsyncSession, sale_id: int) -> Optional[ErpSale]:
    result = await session.execute(select(ErpSale).where(ErpSale.id == sale_id))
    return result.scalar_one_or_none()


async def get_company_rating(session: AsyncSession, seller_inn: str, month_key: str) -> Decimal:
    result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(CAST(REPLACE(volume_total, ',', '.') AS REAL)), 0)
            FROM erp_sales WHERE seller_inn = :seller_inn AND month_key = :month_key
            """
        ),
        {"seller_inn": seller_inn, "month_key": month_key},
    )
    value = result.scalar_one()
    return Decimal(str(value))


async def get_personal_rating(session: AsyncSession, user_id: int, month_key: str) -> Decimal:
    result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(CAST(REPLACE(es.volume_total, ',', '.') AS REAL)), 0)
            FROM sale_confirmations sc
            JOIN erp_sales es ON es.id = sc.sale_id
            WHERE sc.user_id = :user_id AND es.month_key = :month_key
            """
        ),
        {"user_id": user_id, "month_key": month_key},
    )
    value = result.scalar_one()
    return Decimal(str(value))


async def list_company_ratings(session: AsyncSession, month_key: str) -> List[Tuple[str, str, Decimal]]:
    result = await session.execute(
        text(
            """
            SELECT seller_inn, seller_name,
                   SUM(CAST(REPLACE(volume_total, ',', '.') AS REAL)) as total
            FROM erp_sales
            WHERE month_key = :month_key
            GROUP BY seller_inn, seller_name
            ORDER BY total DESC
            """
        ),
        {"month_key": month_key},
    )
    rows = []
    for row in result:
        rows.append((row.seller_inn, row.seller_name, Decimal(str(row.total))))
    return rows


async def list_company_staff_ratings(
    session: AsyncSession, org_id: int, month_key: str
) -> List[Tuple[str, Decimal]]:
    result = await session.execute(
        text(
            """
            SELECT u.full_name,
                   COALESCE(SUM(CAST(REPLACE(es.volume_total, ',', '.') AS REAL)), 0) as total
            FROM users u
            LEFT JOIN sale_confirmations sc ON sc.user_id = u.id
            LEFT JOIN erp_sales es ON es.id = sc.sale_id AND es.month_key = :month_key
            WHERE u.org_id = :org_id
            GROUP BY u.full_name
            ORDER BY total DESC
            """
        ),
        {"org_id": org_id, "month_key": month_key},
    )
    return [(row.full_name, Decimal(str(row.total))) for row in result]


async def get_open_ticket_by_user(session: AsyncSession, user_id: int) -> Optional[SupportTicket]:
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.user_id == user_id, SupportTicket.status == "OPEN"
        )
    )
    return result.scalar_one_or_none()


async def get_ticket_by_thread(session: AsyncSession, thread_id: int) -> Optional[SupportTicket]:
    result = await session.execute(select(SupportTicket).where(SupportTicket.thread_id == thread_id))
    return result.scalar_one_or_none()


async def create_support_ticket(
    session: AsyncSession,
    user_id: int,
    org_id: Optional[int],
    curator_admin_tg_id: Optional[int],
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
    return ticket


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
    text_value: Optional[str],
    file_id: Optional[str],
) -> None:
    message = SupportMessage(
        ticket_id=ticket_id,
        direction=direction,
        msg_type=msg_type,
        text=text_value,
        file_id=file_id,
    )
    session.add(message)
    await session.commit()
