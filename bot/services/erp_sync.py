import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.erp_client import ErpClient
from bot.services.time_utils import get_last_closed_month
from bot.db.repo import upsert_sales


def _normalize_value(value: str | None) -> str:
    return (value or "").strip()


def _decimal_to_str(value: str | None) -> str:
    if value is None:
        return "0,00"
    return str(value)


def build_source_hash(data: dict) -> str:
    parts = [
        _normalize_value(data.get("Период")),
        _normalize_value(data.get("ТипОперации")),
        _normalize_value(data.get("Номенклатура")),
        _normalize_value(data.get("ОбъемТоваров")),
        _normalize_value(data.get("ОбъемЧастичнойРеализации")),
        _normalize_value(data.get("ПродавецИНН")),
        _normalize_value(data.get("ПокупательИНН")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_month_key(period: str) -> str:
    dt = datetime.fromisoformat(period)
    return f"{dt.year:04d}-{dt.month:02d}"


def map_sale(data: dict) -> dict:
    return {
        "source_hash": build_source_hash(data),
        "month_key": parse_month_key(data["Период"]),
        "period": data["Период"],
        "operation_type": data.get("ТипОперации"),
        "product_name": data.get("Номенклатура"),
        "volume_total": _decimal_to_str(data.get("ОбъемТоваров")),
        "volume_partial": data.get("ОбъемЧастичнойРеализации"),
        "seller_inn": data.get("ПродавецИНН"),
        "seller_name": data.get("ПродавецНаименование"),
        "buyer_inn": data.get("ПокупательИНН"),
        "buyer_name": data.get("ПокупательНаименование"),
        "loaded_at": datetime.utcnow(),
    }


async def sync_from_erp(session: AsyncSession, timezone: str) -> int:
    _, period_start, period_end = get_last_closed_month(timezone)
    client = ErpClient(Path("1cerpsql"))
    if not client.config.erp_http_url:
        return 0
    data = await client.fetch_sales(period_start, period_end)
    mapped = [map_sale(item) for item in data]
    return await upsert_sales(session, mapped)
