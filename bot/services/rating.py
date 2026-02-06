from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ErpSale, SaleConfirmation, User


async def world_rating(session: AsyncSession, start_date, end_date):
    stmt = (
        select(User.full_name, func.sum(ErpSale.volume_total_l).label("total"))
        .join(SaleConfirmation, SaleConfirmation.tg_id == User.tg_id)
        .join(ErpSale, ErpSale.id == SaleConfirmation.sale_id)
        .where(ErpSale.doc_date >= start_date, ErpSale.doc_date < end_date)
        .group_by(User.tg_id, User.full_name)
        .order_by(func.sum(ErpSale.volume_total_l).desc(), User.full_name.asc())
        .limit(30)
    )
    result = await session.execute(stmt)
    return result.all()
