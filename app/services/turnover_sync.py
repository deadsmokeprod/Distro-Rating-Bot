from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Config
from app.db.sqlite import upsert_chz_turnover
from app.services.onec_client import OnecClientError, OnecTurnoverRow, fetch_chz_turnover

logger = logging.getLogger(__name__)


def current_month_range(today: date) -> tuple[date, date]:
    return today.replace(day=1), today


def last_30_days_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=30), today


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _rows_to_dicts(rows: list[OnecTurnoverRow]) -> list[dict]:
    return [asdict(row) for row in rows]


async def sync_turnover(
    config: Config, start: date, end: date
) -> tuple[int, int]:
    if not config.onec_url:
        raise OnecClientError("ONEC_URL не задан")
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    rows = await fetch_chz_turnover(config.onec_url, start_iso, end_iso)
    upserted = await upsert_chz_turnover(config.db_path, _rows_to_dicts(rows))
    return len(rows), upserted
