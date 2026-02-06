from datetime import datetime, timedelta
from typing import Tuple

import pytz


def get_last_closed_month_range(timezone: str) -> Tuple[datetime, datetime, str]:
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_prev = first_this_month - timedelta(days=1)
    start = last_day_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = last_day_prev.replace(hour=23, minute=59, second=59, microsecond=0)
    month_key = start.strftime("%Y-%m")
    return start, end, month_key


def month_key_from_date(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def list_last_month_keys(count: int, timezone: str) -> Tuple[str, ...]:
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    keys = []
    year = now.year
    month = now.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return tuple(keys)
