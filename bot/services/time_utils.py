from __future__ import annotations

from datetime import datetime, timedelta
from typing import Tuple

import pytz


def get_last_closed_month(timezone: str) -> Tuple[str, datetime, datetime]:
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = first_of_month - timedelta(seconds=1)
    start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_key = start.strftime("%Y-%m")
    return month_key, start, last_month_end


def month_key_from_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def prev_month_key(month_key: str) -> str:
    year, month = map(int, month_key.split("-"))
    month -= 1
    if month == 0:
        month = 12
        year -= 1
    return f"{year}-{str(month).zfill(2)}"


def month_label(month_key: str) -> str:
    year, month = month_key.split("-")
    return f"{month}.{year}"
