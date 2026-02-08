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


def _basic_auth_tuple(config: Config) -> tuple[str, str] | None:
    if config.onec_username and config.onec_password:
        return (config.onec_username, config.onec_password)
    return None


async def sync_turnover(
    config: Config,
    start: date,
    end: date,
    operation_type: str | None = None,
) -> tuple[int, int]:
    if not config.onec_url:
        raise OnecClientError("ONEC_URL не задан")
    op_type = operation_type if operation_type is not None else config.onec_operation_type
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    rows = await fetch_chz_turnover(
        config.onec_url,
        start_iso,
        end_iso,
        operation_type=op_type,
        timeout_seconds=config.onec_timeout_seconds,
        basic_auth=_basic_auth_tuple(config),
    )
    upserted = await upsert_chz_turnover(config.db_path, _rows_to_dicts(rows))
    return len(rows), upserted
