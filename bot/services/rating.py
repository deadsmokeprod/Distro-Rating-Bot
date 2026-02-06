from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ErpSale, SaleConfirmation, User


async def get_world_rating(
    session: AsyncSession,
    month_start: dt.date,
    month_end: dt.date,
) -> Sequence[tuple[str, float]]:
    stmt = (
        select(User.full_name, func.sum(ErpSale.volume_total_l).label("total"))
        .join(SaleConfirmation, SaleConfirmation.tg_id == User.tg_id)
        .join(ErpSale, ErpSale.id == SaleConfirmation.sale_id)
        .where(ErpSale.doc_date.between(month_start, month_end))
        .group_by(User.tg_id)
        .order_by(desc("total"), User.full_name.asc())
        .limit(30)
    )
    result = await session.execute(stmt)
    return [(row[0], float(row[1] or 0)) for row in result.all()]
