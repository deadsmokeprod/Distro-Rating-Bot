from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from app.db import sqlite
from app.utils.time import now_utc_iso


@dataclass(frozen=True)
class RatingRow:
    tg_user_id: int
    org_id: int
    full_name: str
    total_volume: float
    global_rank: int
    company_rank: int


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def month_bounds(target: date) -> tuple[date, date]:
    start = target.replace(day=1)
    last_day = calendar.monthrange(target.year, target.month)[1]
    end = target.replace(day=last_day)
    return start, end


def previous_month(target: date) -> date:
    year = target.year
    month = target.month - 1
    if month == 0:
        month = 12
        year -= 1
    return date(year, month, 1)


def month_str(target: date) -> str:
    return f"{target.year:04d}-{target.month:02d}"


def _assign_ranks(rows: List[Dict[str, Any]]) -> List[RatingRow]:
    sorted_rows = sorted(
        rows,
        key=lambda r: (-r["total_volume"], r["tg_user_id"]),
    )
    global_rank = {}
    for idx, row in enumerate(sorted_rows, start=1):
        global_rank[row["tg_user_id"]] = idx

    company_rank_map: Dict[int, Dict[int, int]] = {}
    for org_id in {r["org_id"] for r in sorted_rows}:
        org_rows = [r for r in sorted_rows if r["org_id"] == org_id]
        company_rank_map[org_id] = {
            r["tg_user_id"]: idx for idx, r in enumerate(org_rows, start=1)
        }

    result: List[RatingRow] = []
    for row in sorted_rows:
        result.append(
            RatingRow(
                tg_user_id=row["tg_user_id"],
                org_id=row["org_id"],
                full_name=row["full_name"],
                total_volume=float(row["total_volume"]),
                global_rank=global_rank[row["tg_user_id"]],
                company_rank=company_rank_map[row["org_id"]][row["tg_user_id"]],
            )
        )
    return result


async def _totals_for_period(db_path: str, start: date | None, end: date | None) -> List[Dict]:
    if start and end:
        query = """
            SELECT
                u.tg_user_id AS tg_user_id,
                u.org_id AS org_id,
                COALESCE(u.full_name, '') AS full_name,
                COALESCE(SUM(CASE
                    WHEN substr(c.claimed_at, 1, 10) BETWEEN ? AND ? THEN t.volume_goods
                END), 0) AS total_volume
            FROM users u
            LEFT JOIN sales_claims c ON c.claimed_by_tg_user_id = u.tg_user_id
            LEFT JOIN chz_turnover t ON t.id = c.turnover_id
            WHERE u.role = 'seller'
            GROUP BY u.tg_user_id, u.org_id, u.full_name
        """
        rows = await sqlite.fetch_all(db_path, query, (start.isoformat(), end.isoformat()))
    else:
        query = """
            SELECT
                u.tg_user_id AS tg_user_id,
                u.org_id AS org_id,
                COALESCE(u.full_name, '') AS full_name,
                COALESCE(SUM(t.volume_goods), 0) AS total_volume
            FROM users u
            LEFT JOIN sales_claims c ON c.claimed_by_tg_user_id = u.tg_user_id
            LEFT JOIN chz_turnover t ON t.id = c.turnover_id
            WHERE u.role = 'seller'
            GROUP BY u.tg_user_id, u.org_id, u.full_name
        """
        rows = await sqlite.fetch_all(db_path, query)
    return [dict(r) for r in rows]


async def current_month_rankings(db_path: str) -> List[RatingRow]:
    today = moscow_today()
    start, end = month_bounds(today)
    totals = await _totals_for_period(db_path, start, end)
    return _assign_ranks(totals)


async def all_time_rankings(db_path: str) -> List[RatingRow]:
    totals = await _totals_for_period(db_path, None, None)
    return _assign_ranks(totals)


async def recalc_all_time_ratings(db_path: str) -> List[RatingRow]:
    rows = await all_time_rankings(db_path)
    await sqlite.execute(db_path, "DELETE FROM ratings_all_time")
    now_iso = now_utc_iso()
    params = [
        (
            r.tg_user_id,
            r.org_id,
            r.full_name,
            r.total_volume,
            r.global_rank,
            r.company_rank,
            now_iso,
        )
        for r in rows
    ]
    # Use executemany via aiosqlite directly for bulk insert
    if params:
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            await db.executemany(
                """
                INSERT INTO ratings_all_time
                    (tg_user_id, org_id, full_name, total_volume, global_rank, company_rank, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            await db.commit()
    return rows


async def write_monthly_snapshot(db_path: str, target: date) -> List[RatingRow]:
    start, end = month_bounds(target)
    rows = _assign_ranks(await _totals_for_period(db_path, start, end))
    m_str = month_str(target)
    await sqlite.execute(db_path, "DELETE FROM ratings_monthly WHERE month = ?", (m_str,))
    params = [
        (
            m_str,
            r.tg_user_id,
            r.org_id,
            r.full_name,
            r.total_volume,
            r.global_rank,
            r.company_rank,
            now_utc_iso(),
        )
        for r in rows
    ]
    if params:
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            await db.executemany(
                """
                INSERT INTO ratings_monthly
                    (month, tg_user_id, org_id, full_name, total_volume, global_rank, company_rank, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            await db.commit()
    return rows


async def get_monthly_snapshot_for_user(
    db_path: str, target: date, tg_user_id: int
) -> Dict[str, Any] | None:
    m_str = month_str(target)
    row = await sqlite.fetch_one(
        db_path,
        """
        SELECT total_volume, global_rank, company_rank
        FROM ratings_monthly
        WHERE month = ? AND tg_user_id = ?
        """,
        (m_str, tg_user_id),
    )
    return dict(row) if row else None


async def get_all_time_for_user(db_path: str, tg_user_id: int) -> Dict[str, Any] | None:
    row = await sqlite.fetch_one(
        db_path,
        """
        SELECT total_volume, global_rank, company_rank
        FROM ratings_all_time
        WHERE tg_user_id = ?
        """,
        (tg_user_id,),
    )
    return dict(row) if row else None
