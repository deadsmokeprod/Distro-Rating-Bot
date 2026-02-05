from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


MONTH_NAMES = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]



def get_last_closed_month(timezone: str) -> datetime:
    now = datetime.now(ZoneInfo(timezone))
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = first_of_month - timedelta(seconds=1)
    return last_month_end



def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")



def month_label(dt: datetime) -> str:
    return f"{MONTH_NAMES[dt.month - 1]} {dt.year}"



def month_range(dt: datetime):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = next_month - timedelta(seconds=1)
    return start, end



def get_recent_months(timezone: str, count: int = 10):
    current = datetime.now(ZoneInfo(timezone)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months = []
    for _ in range(count):
        months.append(current)
        current = (current - timedelta(days=1)).replace(day=1)
    return months


def previous_month(dt: datetime) -> datetime:
    return (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
