from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from pytz import timezone as tz

logger = logging.getLogger(__name__)


def parse_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.replace(",", ".").strip()
        try:
            return float(raw)
        except ValueError:
            logger.warning("Failed to parse float from %s", value)
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Failed to parse float from %s", value)
        return 0.0


def parse_date(value: object) -> Optional[dt.date]:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return dt.datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def month_range(timezone_name: str) -> tuple[dt.date, dt.date, str]:
    tzinfo = tz(timezone_name)
    now = dt.datetime.now(tzinfo)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
    if now.month == 12:
        end_month = dt.date(now.year + 1, 1, 1)
    else:
        end_month = dt.date(now.year, now.month + 1, 1)
    return start, end_month, now.strftime("%Y-%m")
