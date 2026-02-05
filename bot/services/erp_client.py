import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import httpx
from .time_utils import month_key


class ErpClient:
    def __init__(self, url: str, user: str, password: str, timeout_sec: int):
        self.url = url
        self.user = user
        self.password = password
        self.timeout = timeout_sec
        self.query = Path("1cerpsql").read_text(encoding="utf-8")

    async def fetch_sales(self, start: datetime, end: datetime) -> list[dict]:
        if not self.url:
            return []
        payload = {
            "query": self.query,
            "params": {
                "НачалоПериода": start.strftime("%Y-%m-%d %H:%M:%S"),
                "КонецПериода": end.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
        auth = (self.user, self.password) if self.user or self.password else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=payload, auth=auth)
            response.raise_for_status()
            data = response.json()
        return [self._normalize(row) for row in data]

    def _normalize(self, row: dict) -> dict:
        period = row.get("Период") or row.get("period")
        period_str = str(period)
        month_key_value = month_key(datetime.fromisoformat(period_str[:19]))
        volume_total = str(row.get("ОбъемТоваров") or row.get("volume_total") or "0")
        volume_partial = str(row.get("ОбъемЧастичнойРеализации") or row.get("volume_partial") or "0")
        seller_inn = str(row.get("ПродавецИНН") or row.get("seller_inn") or "")
        buyer_inn = str(row.get("ПокупательИНН") or row.get("buyer_inn") or "")
        source_hash = self._hash_source(
            period_str,
            str(row.get("ТипОперации") or row.get("operation_type") or ""),
            str(row.get("Номенклатура") or row.get("product_name") or ""),
            volume_total,
            volume_partial,
            seller_inn,
            buyer_inn,
        )
        return {
            "source_hash": source_hash,
            "month_key": month_key_value,
            "period": period_str,
            "operation_type": row.get("ТипОперации") or row.get("operation_type"),
            "product_name": row.get("Номенклатура") or row.get("product_name"),
            "volume_total": volume_total,
            "volume_partial": volume_partial,
            "seller_inn": seller_inn,
            "seller_name": row.get("ПродавецНаименование") or row.get("seller_name"),
            "buyer_inn": buyer_inn,
            "buyer_name": row.get("ПокупательНаименование") or row.get("buyer_name"),
            "loaded_at": datetime.utcnow(),
        }

    def _hash_source(self, *parts: str) -> str:
        normalized = "|".join(part.strip() for part in parts)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
