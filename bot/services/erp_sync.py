from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable

from bot.db.repo import commit_sales, upsert_erp_sale
from bot.services.erp_client import fetch_sales
from bot.services.time_utils import month_key_from_date


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def build_source_hash(row: Dict[str, Any]) -> str:
    raw = "|".join(
        [
            _normalize(row.get("Период")),
            _normalize(row.get("ТипОперации")),
            _normalize(row.get("Номенклатура")),
            _normalize(row.get("ОбъемТоваров")),
            _normalize(row.get("ОбъемЧастичнойРеализации")),
            _normalize(row.get("ПродавецИНН")),
            _normalize(row.get("ПокупательИНН")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_period(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def sync_erp(session, start: datetime, end: datetime, default_month_key: str) -> int:
    rows = await fetch_sales(start, end)
    count = 0
    for row in rows:
        period = _normalize(row.get("Период"))
        period_dt = parse_period(period)
        month_key = month_key_from_date(period_dt) if period_dt else default_month_key
        volume_total = _normalize(row.get("ОбъемТоваров")).replace(",", ".") or "0"
        volume_partial = _normalize(row.get("ОбъемЧастичнойРеализации")).replace(",", ".")
        data = {
            "source_hash": build_source_hash(row),
            "month_key": month_key,
            "period": period,
            "operation_type": _normalize(row.get("ТипОперации")),
            "product_name": _normalize(row.get("Номенклатура")),
            "volume_total": volume_total,
            "volume_partial": volume_partial,
            "seller_inn": _normalize(row.get("ПродавецИНН")),
            "seller_name": _normalize(row.get("ПродавецНаименование")),
            "buyer_inn": _normalize(row.get("ПокупательИНН")),
            "buyer_name": _normalize(row.get("ПокупательНаименование")),
            "loaded_at": datetime.utcnow(),
        }
        await upsert_erp_sale(session, data)
        count += 1
    await commit_sales(session)
    return count
