from __future__ import annotations

from datetime import datetime, timezone


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_iso_human(iso_value: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    return dt.strftime("%Y-%m-%d %H:%M:%S")
