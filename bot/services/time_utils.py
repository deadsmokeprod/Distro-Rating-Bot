from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def get_last_closed_month(timezone: str) -> tuple[str, datetime, datetime]:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    first_day_current = datetime(now.year, now.month, 1, tzinfo=tz)
    last_month_end = first_day_current.replace(second=0, microsecond=0) - timedelta(seconds=1)
    last_month_start = datetime(last_month_end.year, last_month_end.month, 1, tzinfo=tz)
    month_key = f"{last_month_end.year:04d}-{last_month_end.month:02d}"
    return month_key, last_month_start, last_month_end


def to_month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"
