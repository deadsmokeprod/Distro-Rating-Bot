from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx

from bot.config import load_config


def load_query() -> str:
    base_dir = Path(__file__).resolve().parent.parent
    query_path = base_dir / "1cerpsql"
    return query_path.read_text(encoding="utf-8")


def build_payload(start: datetime, end: datetime) -> dict:
    query = load_query()
    return {
        "query": query,
        "params": {
            "НачалоПериода": start.strftime("%Y-%m-%d %H:%M:%S"),
            "КонецПериода": end.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


async def fetch_sales(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    config = load_config()
    if not config.erp_http_url:
        return []
    payload = build_payload(start, end)
    auth = None
    if config.erp_http_user and config.erp_http_password:
        auth = (config.erp_http_user, config.erp_http_password)
    async with httpx.AsyncClient(timeout=config.erp_timeout_sec) as client:
        response = await client.post(config.erp_http_url, json=payload, auth=auth)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        return []
    return data
