from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

from app.config import Config
from app.db import sqlite
from app.services.ratings import month_bounds, month_str
from app.utils.time import now_utc_iso


@dataclass(frozen=True)
class Challenge:
    tg_user_id: int
    period_start: str
    period_end: str
    target_volume: float
    progress_volume: float
    completed: int


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def biweekly_period_for(target: date) -> tuple[date, date]:
    if target.day <= 14:
        start = target.replace(day=1)
        end = target.replace(day=14)
    else:
        start = target.replace(day=15)
        end = month_bounds(target)[1]
    return start, end


async def _last_month_volume(db_path: str, tg_user_id: int) -> float:
    today = moscow_today()
    last_month = (today.replace(day=1) - date.resolution)
    start, end = month_bounds(last_month)
    row = await sqlite.fetch_one(
        db_path,
        """
        SELECT COALESCE(SUM(t.volume_goods), 0) AS total_volume
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND substr(t.period, 1, 10) BETWEEN ? AND ?
        """,
        (tg_user_id, start.isoformat(), end.isoformat()),
    )
    return float(row["total_volume"]) if row else 0.0


def _calc_target(last_month_volume: float, cfg: Config) -> float:
    if last_month_volume <= 0:
        return cfg.challenge_base_volume
    return max(
        cfg.challenge_base_volume,
        last_month_volume * (1 + cfg.challenge_growth_pct / 100.0),
    )


async def ensure_biweekly_challenges(cfg: Config) -> None:
    today = moscow_today()
    start, end = biweekly_period_for(today)
    period_start = start.isoformat()
    period_end = end.isoformat()
    users = await sqlite.fetch_all(
        cfg.db_path,
        "SELECT tg_user_id FROM users WHERE role IN ('seller','rop') AND status = 'active'",
    )
    for row in users:
        tg_user_id = int(row["tg_user_id"])
        exists = await sqlite.fetch_one(
            cfg.db_path,
            """
            SELECT id FROM challenges_biweekly
            WHERE tg_user_id = ? AND period_start = ? AND period_end = ?
            """,
            (tg_user_id, period_start, period_end),
        )
        if exists:
            continue
        last_month_volume = await _last_month_volume(cfg.db_path, tg_user_id)
        target = _calc_target(last_month_volume, cfg)
        await sqlite.execute(
            cfg.db_path,
            """
            INSERT INTO challenges_biweekly
                (tg_user_id, period_start, period_end, target_volume, progress_volume, completed, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, ?)
            """,
            (tg_user_id, period_start, period_end, target, now_utc_iso()),
        )


async def get_current_challenge(cfg: Config, tg_user_id: int) -> Challenge | None:
    today = moscow_today()
    start, end = biweekly_period_for(today)
    row = await sqlite.fetch_one(
        cfg.db_path,
        """
        SELECT tg_user_id, period_start, period_end, target_volume, progress_volume, completed
        FROM challenges_biweekly
        WHERE tg_user_id = ? AND period_start = ? AND period_end = ?
        """,
        (tg_user_id, start.isoformat(), end.isoformat()),
    )
    return Challenge(**dict(row)) if row else None


async def update_challenge_progress(cfg: Config, tg_user_id: int) -> tuple[Challenge | None, bool]:
    today = moscow_today()
    start, end = biweekly_period_for(today)
    row = await sqlite.fetch_one(
        cfg.db_path,
        """
        SELECT COALESCE(SUM(t.volume_goods), 0) AS total_volume
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND substr(t.period, 1, 10) BETWEEN ? AND ?
        """,
        (tg_user_id, start.isoformat(), end.isoformat()),
    )
    progress = float(row["total_volume"]) if row else 0.0
    await sqlite.execute(
        cfg.db_path,
        """
        UPDATE challenges_biweekly
        SET progress_volume = ?, updated_at = ?
        WHERE tg_user_id = ? AND period_start = ? AND period_end = ?
        """,
        (progress, now_utc_iso(), tg_user_id, start.isoformat(), end.isoformat()),
    )
    challenge = await get_current_challenge(cfg, tg_user_id)
    just_completed = False
    if challenge and not challenge.completed and progress >= challenge.target_volume:
        await sqlite.execute(
            cfg.db_path,
            """
            UPDATE challenges_biweekly
            SET completed = 1, updated_at = ?
            WHERE tg_user_id = ? AND period_start = ? AND period_end = ?
            """,
            (now_utc_iso(), tg_user_id, start.isoformat(), end.isoformat()),
        )
        just_completed = True
        challenge = await get_current_challenge(cfg, tg_user_id)
    return challenge, just_completed
