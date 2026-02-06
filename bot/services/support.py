from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SupportTicket


async def get_open_ticket(session: AsyncSession, tg_id: int) -> SupportTicket | None:
    return await session.scalar(
        select(SupportTicket).where(SupportTicket.tg_id == tg_id, SupportTicket.status == "open")
    )


async def get_open_ticket_by_topic(session: AsyncSession, topic_id: int) -> SupportTicket | None:
    return await session.scalar(
        select(SupportTicket).where(SupportTicket.topic_id == topic_id, SupportTicket.status == "open")
    )
