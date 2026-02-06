from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

import pytz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ErpSale, SaleConfirmation, User


def get_month_range(timezone: str) -> tuple[date, date]:
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    start = date(now.year, now.month, 1)
    if now.month == 12:
        end = date(now.year + 1, 1, 1)
    else:
        end = date(now.year, now.month + 1, 1)
    return start, end


async def get_world_rating(session: AsyncSession, timezone: str) -> Sequence[tuple[str, float]]:
    start, end = get_month_range(timezone)
    stmt = (
        select(User.full_name, func.sum(ErpSale.volume_total_l).label("total_l"))
        .join(SaleConfirmation, SaleConfirmation.tg_id == User.tg_id)
        .join(ErpSale, ErpSale.id == SaleConfirmation.sale_id)
        .where(ErpSale.doc_date >= start, ErpSale.doc_date < end)
        .group_by(User.full_name)
        .order_by(func.sum(ErpSale.volume_total_l).desc(), User.full_name.asc())
        .limit(30)
    )
    result = await session.execute(stmt)
    return [(row[0], float(row[1] or 0.0)) for row in result.all()]
