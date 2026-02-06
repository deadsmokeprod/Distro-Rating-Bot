from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Tuple

import httpx
from sqlalchemy import insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ErpSale
from ..utils import parse_date, parse_float

logger = logging.getLogger(__name__)


async def fetch_sales(erp_url: str, username: str, password: str) -> List[Dict[str, Any]]:
    if not erp_url:
        logger.warning("ERP_URL is empty, skipping sync")
        return []
    auth = (username, password) if username or password else None
    timeout = httpx.Timeout(20.0)
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(erp_url, auth=auth)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    return payload
                if isinstance(payload, dict) and "items" in payload:
                    return payload.get("items", [])
                logger.warning("Unexpected ERP payload format")
                return []
        except httpx.HTTPError as exc:
            logger.warning("ERP request failed (attempt %s): %s", attempt + 1, exc)
            if attempt == 1:
                raise
    return []


async def sync_sales(
    session: AsyncSession,
    erp_url: str,
    username: str,
    password: str,
) -> Tuple[int, int]:
    added = 0
    updated = 0
    try:
        items = await fetch_sales(erp_url, username, password)
        for item in items:
            doc_number = str(item.get("doc_number") or item.get("docNumber") or "").strip()
            doc_date = parse_date(item.get("doc_date") or item.get("docDate"))
            seller_inn = str(item.get("seller_inn") or item.get("sellerInn") or "").strip()
            if not doc_number or not doc_date or not seller_inn:
                logger.warning("Skipping invalid sale payload: %s", item)
                continue
            buyer_name = item.get("buyer_name") or item.get("buyerName")
            volume_total_l = parse_float(item.get("volume_total_l") or item.get("volumeTotalL"))
            existing = await session.execute(
                select(ErpSale.id).where(
                    ErpSale.seller_inn == seller_inn,
                    ErpSale.doc_number == doc_number,
                    ErpSale.doc_date == doc_date,
                )
            )
            existed_before = existing.scalar_one_or_none() is not None

            stmt = insert(ErpSale).values(
                seller_inn=seller_inn,
                doc_number=doc_number,
                doc_date=doc_date,
                buyer_name=buyer_name,
                volume_total_l=volume_total_l,
                updated_at=dt.datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["seller_inn", "doc_number", "doc_date"],
                set_={
                    "buyer_name": buyer_name,
                    "volume_total_l": volume_total_l,
                    "updated_at": dt.datetime.utcnow(),
                },
            )
            await session.execute(stmt)
            if existed_before:
                updated += 1
            else:
                added += 1
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Database error during ERP sync")
        raise
    return added, updated
