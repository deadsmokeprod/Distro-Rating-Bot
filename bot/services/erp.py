from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ErpSale, SyncStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ErpSalePayload:
    seller_inn: str
    doc_number: str
    doc_date: dt.date
    buyer_name: str | None
    volume_total_l: float


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            logger.warning("Failed to parse volume '%s'", value)
            return 0.0
    return 0.0


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d"):
            try:
                return dt.datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


async def fetch_sales(url: str, username: str, password: str) -> list[ErpSalePayload]:
    if not url:
        logger.warning("ERP_URL is empty, skipping sync")
        return []

    timeout = httpx.Timeout(20.0)
    retries = 2
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, auth=(username, password))
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    logger.warning("Unexpected ERP payload format")
                    return []
                results: list[ErpSalePayload] = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    seller_inn = str(item.get("seller_inn") or item.get("ИННПродавца") or "").strip()
                    doc_number = str(item.get("doc_number") or item.get("НомерДок") or "").strip()
                    doc_date_raw = item.get("doc_date") or item.get("ДатаДок")
                    doc_date = _parse_date(doc_date_raw)
                    buyer_name = item.get("buyer_name") or item.get("Покупатель")
                    volume_total_l = _parse_float(item.get("volume_total_l") or item.get("Литры"))
                    if not seller_inn or not doc_number or not doc_date:
                        logger.warning("Skipping invalid ERP record: %s", item)
                        continue
                    results.append(
                        ErpSalePayload(
                            seller_inn=seller_inn,
                            doc_number=doc_number,
                            doc_date=doc_date,
                            buyer_name=str(buyer_name) if buyer_name else None,
                            volume_total_l=volume_total_l,
                        )
                    )
                return results
        except Exception as exc:
            last_error = exc
            logger.exception("Failed to fetch ERP data")
    if last_error:
        raise last_error
    return []


async def upsert_sales(session: AsyncSession, sales: list[ErpSalePayload]) -> tuple[int, int]:
    added = 0
    updated = 0
    for sale in sales:
        stmt = (
            insert(ErpSale)
            .values(
                seller_inn=sale.seller_inn,
                doc_number=sale.doc_number,
                doc_date=sale.doc_date,
                buyer_name=sale.buyer_name,
                volume_total_l=sale.volume_total_l,
            )
            .on_conflict_do_update(
                index_elements=["seller_inn", "doc_number", "doc_date"],
                set_={
                    "buyer_name": sale.buyer_name,
                    "volume_total_l": sale.volume_total_l,
                    "updated_at": dt.datetime.utcnow(),
                },
            )
        )
        result = await session.execute(stmt)
        if result.rowcount == 1:
            added += 1
        else:
            updated += 1
    return added, updated


async def save_sync_status(session: AsyncSession, added: int, updated: int, error: str | None) -> None:
    status = await session.scalar(select(SyncStatus).where(SyncStatus.id == 1))
    if not status:
        status = SyncStatus(id=1)
        session.add(status)
    status.last_run_at = dt.datetime.utcnow()
    status.last_error = error
    status.added = added
    status.updated = updated


async def sync_erp_sales(session: AsyncSession, url: str, username: str, password: str) -> tuple[int, int]:
    added = 0
    updated = 0
    error_message: str | None = None
    try:
        sales = await fetch_sales(url, username, password)
        added, updated = await upsert_sales(session, sales)
    except Exception as exc:
        error_message = str(exc)
        logger.exception("ERP sync failed")
    await save_sync_status(session, added, updated, error_message)
    return added, updated
