from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ErpSale, SyncStatus
from bot.utils import parse_date, parse_float

logger = logging.getLogger(__name__)


class ErpSyncError(Exception):
    pass


def _normalize_sales(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "sales" in data and isinstance(data["sales"], list):
        return data["sales"]
    return []


async def fetch_sales(url: str, username: str, password: str, timeout_s: float = 20.0) -> list[dict[str, Any]]:
    if not url:
        raise ErpSyncError("ERP_URL is missing")
    auth = (username, password) if username or password else None
    tries = 2
    for attempt in range(1, tries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(url, auth=auth)
                response.raise_for_status()
                return _normalize_sales(response.json())
        except httpx.HTTPError as exc:
            logger.warning("ERP request failed (attempt %s/%s): %s", attempt, tries, exc)
            if attempt == tries:
                raise ErpSyncError("ERP request failed") from exc
    return []


async def upsert_sales(session: AsyncSession, sales: list[dict[str, Any]]) -> tuple[int, int]:
    added = 0
    updated = 0
    for item in sales:
        doc_number = str(item.get("doc_number") or item.get("number") or "").strip()
        doc_date = parse_date(item.get("doc_date") or item.get("date"))
        seller_inn = str(item.get("seller_inn") or item.get("inn") or "").strip()
        if not doc_number or not doc_date or not seller_inn:
            logger.warning("ERP record missing required fields: %s", item)
            continue
        buyer_name = item.get("buyer_name") or item.get("buyer")
        volume_total_l = parse_float(item.get("volume_total_l") or item.get("liters") or item.get("volume"))

        exists_stmt = select(ErpSale.id).where(
            ErpSale.seller_inn == seller_inn,
            ErpSale.doc_number == doc_number,
            ErpSale.doc_date == doc_date,
        )
        exists = await session.execute(exists_stmt)
        was_existing = exists.scalar_one_or_none() is not None

        payload = {
            "seller_inn": seller_inn,
            "doc_number": doc_number,
            "doc_date": doc_date,
            "buyer_name": buyer_name,
            "volume_total_l": volume_total_l,
            "updated_at": datetime.utcnow(),
        }
        stmt = (
            insert(ErpSale)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=[ErpSale.seller_inn, ErpSale.doc_number, ErpSale.doc_date],
                set_=payload,
            )
        )
        await session.execute(stmt)
        if was_existing:
            updated += 1
        else:
            added += 1
    return added, updated


async def record_sync_success(session: AsyncSession) -> None:
    status = await session.get(SyncStatus, 1)
    if status is None:
        status = SyncStatus(id=1)
        session.add(status)
    status.last_success_at = datetime.utcnow()
    status.last_error = None
    status.last_error_at = None


async def record_sync_error(session: AsyncSession, message: str) -> None:
    status = await session.get(SyncStatus, 1)
    if status is None:
        status = SyncStatus(id=1)
        session.add(status)
    status.last_error = message
    status.last_error_at = datetime.utcnow()


async def get_sync_status(session: AsyncSession) -> SyncStatus | None:
    result = await session.execute(select(SyncStatus).where(SyncStatus.id == 1))
    return result.scalar_one_or_none()
