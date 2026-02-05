from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from bot.db.repo import get_org_rating, get_personal_rating, list_org_ratings, list_personal_ratings_for_org


def parse_decimal(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    return Decimal(str(value).replace(",", "."))


async def get_org_rating_with_previous(session, inn: str, month_key: str, prev_month_key: str) -> Tuple[Decimal, Decimal]:
    current = await get_org_rating(session, inn, month_key)
    prev = await get_org_rating(session, inn, prev_month_key)
    return current, prev


async def get_personal_rating_with_previous(session, user_id: int, month_key: str, prev_month_key: str) -> Tuple[Decimal, Decimal]:
    current = await get_personal_rating(session, user_id, month_key)
    prev = await get_personal_rating(session, user_id, prev_month_key)
    return current, prev


async def build_org_ranking(session, month_key: str) -> List[Tuple[str, str, Decimal]]:
    return await list_org_ratings(session, month_key)


async def build_personal_ranking_for_org(session, org_id: int, month_key: str) -> List[Tuple[str, Decimal]]:
    return await list_personal_ratings_for_org(session, org_id, month_key)
