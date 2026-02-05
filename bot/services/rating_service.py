from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ErpSale, SaleConfirmation, User


def parse_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


async def company_rating(session: AsyncSession, seller_inn: str, month_key: str) -> Decimal:
    result = await session.execute(
        select(ErpSale.volume_total).where(
            ErpSale.seller_inn == seller_inn, ErpSale.month_key == month_key
        )
    )
    total = Decimal("0")
    for (volume,) in result.all():
        total += parse_decimal(volume)
    return total


async def user_rating(session: AsyncSession, user_id: int, month_key: str) -> Decimal:
    result = await session.execute(
        select(ErpSale.volume_total)
        .join(SaleConfirmation, SaleConfirmation.sale_id == ErpSale.id)
        .where(SaleConfirmation.user_id == user_id)
        .where(ErpSale.month_key == month_key)
    )
    total = Decimal("0")
    for (volume,) in result.all():
        total += parse_decimal(volume)
    return total


async def company_rankings(session: AsyncSession, month_key: str) -> list[tuple[str, str, Decimal]]:
    result = await session.execute(
        select(ErpSale.seller_inn, ErpSale.seller_name, ErpSale.volume_total).where(
            ErpSale.month_key == month_key
        )
    )
    totals: dict[str, tuple[str, Decimal]] = {}
    for seller_inn, seller_name, volume in result.all():
        current_name, current_total = totals.get(seller_inn, (seller_name or "", Decimal("0")))
        totals[seller_inn] = (current_name or seller_name or "", current_total + parse_decimal(volume))
    rankings = [(inn, name, total) for inn, (name, total) in totals.items()]
    rankings.sort(key=lambda item: item[2], reverse=True)
    return rankings


async def org_members_ratings(session: AsyncSession, org_id: int, month_key: str) -> list[tuple[str, Decimal]]:
    result = await session.execute(select(User).where(User.org_id == org_id))
    users = result.scalars().all()
    ratings = []
    for user in users:
        total = await user_rating(session, user.id, month_key)
        ratings.append((user.full_name, total))
    return ratings
