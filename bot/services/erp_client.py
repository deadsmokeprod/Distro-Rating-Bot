import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from bot.config import load_config


class ErpClient:
    def __init__(self, query_path: Path) -> None:
        self.config = load_config()
        self.query_path = query_path

    def _load_query(self) -> str:
        return self.query_path.read_text(encoding="utf-8")

    async def fetch_sales(self, period_start: datetime, period_end: datetime) -> list[dict[str, Any]]:
        payload = {
            "query": self._load_query(),
            "params": {
                "НачалоПериода": period_start.isoformat(),
                "КонецПериода": period_end.isoformat(),
            },
        }
        auth = None
        if self.config.erp_http_user and self.config.erp_http_password:
            auth = (self.config.erp_http_user, self.config.erp_http_password)

        async with httpx.AsyncClient(timeout=self.config.erp_timeout_sec) as client:
            response = await client.post(
                self.config.erp_http_url,
                json=payload,
                auth=auth,
            )
            response.raise_for_status()
            data = response.json()

        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            raise ValueError("ERP response is not a list")
        return data
