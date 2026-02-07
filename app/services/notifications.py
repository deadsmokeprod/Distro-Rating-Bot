from __future__ import annotations

import json
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from app.config import Config
from app.db import sqlite
from app.utils.time import now_utc_iso


def moscow_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Moscow"))


def _parse_hhmm(value: str) -> dtime:
    parts = value.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return dtime(hour=hour, minute=minute)


def is_quiet_time(cfg: Config, now: datetime | None = None) -> bool:
    now = now or moscow_now()
    start = _parse_hhmm(cfg.quiet_hours_start)
    end = _parse_hhmm(cfg.quiet_hours_end)
    current = now.time()
    if start < end:
        return start <= current < end
    # crosses midnight
    return current >= start or current < end


async def can_send_weekly(db_path: str, tg_user_id: int) -> bool:
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    row = await sqlite.fetch_one(
        db_path,
        """
        SELECT 1 AS exists_flag
        FROM notifications
        WHERE tg_user_id = ? AND status = 'sent' AND sent_at >= ?
        LIMIT 1
        """,
        (tg_user_id, week_ago),
    )
    return row is None


async def record_notification(
    db_path: str,
    tg_user_id: int,
    kind: str,
    status: str,
    context: dict | None = None,
) -> None:
    await sqlite.execute(
        db_path,
        """
        INSERT INTO notifications (tg_user_id, kind, context_json, scheduled_at, sent_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tg_user_id,
            kind,
            json.dumps(context, ensure_ascii=False) if context else None,
            now_utc_iso(),
            now_utc_iso() if status == "sent" else None,
            status,
            now_utc_iso(),
        ),
    )
