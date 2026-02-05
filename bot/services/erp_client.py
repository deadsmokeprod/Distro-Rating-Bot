import hashlib
from datetime import datetime
from typing import List

import httpx


def build_source_hash(row: dict) -> str:
    raw = "|".join(
        [
            str(row.get("Период", "")),
            str(row.get("ТипОперации", "")),
            str(row.get("Номенклатура", "")),
            str(row.get("ОбъемТоваров", "")),
            str(row.get("ОбъемЧастичнойРеализации", "")),
            str(row.get("ПродавецИНН", "")),
            str(row.get("ПокупательИНН", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_row(row: dict, month_key: str) -> dict:
    return {
        "source_hash": build_source_hash(row),
        "month_key": month_key,
        "period": str(row.get("Период", "")),
        "operation_type": row.get("ТипОперации"),
        "product_name": row.get("Номенклатура"),
        "volume_total": str(row.get("ОбъемТоваров", "0")),
        "volume_partial": str(row.get("ОбъемЧастичнойРеализации", "")),
        "seller_inn": str(row.get("ПродавецИНН", "")),
        "seller_name": row.get("ПродавецНаименование"),
        "buyer_inn": str(row.get("ПокупательИНН", "")),
        "buyer_name": row.get("ПокупательНаименование"),
        "loaded_at": datetime.utcnow(),
    }


async def fetch_erp_sales(
    url: str,
    user: str,
    password: str,
    query: str,
    start_period: str,
    end_period: str,
    timeout_sec: int,
) -> List[dict]:
    payload = {
        "query": query,
        "params": {"НачалоПериода": start_period, "КонецПериода": end_period},
    }
    auth = (user, password) if user or password else None
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        response = await client.post(url, json=payload, auth=auth)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise ValueError("ERP response must be a JSON array")
    return data
