from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.models import ErpSale, SaleConfirmation, Organization, User


def parse_decimal(value: str) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value).replace(",", "."))


async def company_rating(session: AsyncSession, seller_inn: str, month_key: str) -> Decimal:
    result = await session.execute(
        select(ErpSale.volume_total)
        .where(and_(ErpSale.seller_inn == seller_inn, ErpSale.month_key == month_key))
    )
    total = Decimal("0")
    for (volume,) in result.all():
        total += parse_decimal(volume)
    return total


async def personal_rating(session: AsyncSession, user_id: int, month_key: str) -> Decimal:
    result = await session.execute(
        select(ErpSale.volume_total)
        .join(SaleConfirmation, SaleConfirmation.sale_id == ErpSale.id)
        .where(and_(SaleConfirmation.user_id == user_id, ErpSale.month_key == month_key))
    )
    total = Decimal("0")
    for (volume,) in result.all():
        total += parse_decimal(volume)
    return total


async def ranking_all_companies(session: AsyncSession, month_key: str):
    result = await session.execute(select(Organization))
    orgs = result.scalars().all()
    ratings = []
    for org in orgs:
        rating = await company_rating(session, org.inn, month_key)
        ratings.append((org, rating))
    ratings.sort(key=lambda item: item[1], reverse=True)
    return ratings


async def ranking_users_in_org(session: AsyncSession, org_id: int, month_key: str):
    result = await session.execute(select(User).where(User.org_id == org_id))
    users = result.scalars().all()
    ratings = []
    for user in users:
        rating = await personal_rating(session, user.id, month_key)
        ratings.append((user, rating))
    ratings.sort(key=lambda item: item[1], reverse=True)
    return ratings
