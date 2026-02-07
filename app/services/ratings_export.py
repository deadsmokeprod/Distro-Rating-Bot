from __future__ import annotations

import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook

from app.db import sqlite
from app.services.ratings import RatingRow, current_month_rankings, month_str


def _month_to_label(month: str) -> str:
    # month in YYYY-MM -> "MM YYYY"
    return f"{month[5:7]} {month[0:4]}"


async def _org_map(db_path: str) -> Dict[int, Dict[str, str]]:
    rows = await sqlite.fetch_all(db_path, "SELECT id, inn, name FROM organizations")
    return {int(r["id"]): {"inn": r["inn"], "name": r["name"]} for r in rows}


async def _monthly_rows(db_path: str, start_month: str, end_month: str) -> List[Dict]:
    rows = await sqlite.fetch_all(
        db_path,
        """
        SELECT m.month, m.tg_user_id, m.full_name, m.org_id,
               m.total_volume, m.global_rank, m.company_rank
        FROM ratings_monthly m
        WHERE m.month BETWEEN ? AND ?
        ORDER BY m.month ASC, m.global_rank ASC
        """,
        (start_month, end_month),
    )
    return [dict(r) for r in rows]


async def _current_month_rows(db_path: str) -> List[RatingRow]:
    return await current_month_rankings(db_path)


def _write_header(ws) -> None:
    ws.append(
        [
            "Период",
            "Пользователь id",
            "Пользователь ФИО",
            "ИНН организации",
            "Наименование организации",
            "Рейтинг",
            "Место в рейтенге мировом",
            "Место в рейтинге компании",
        ]
    )


def _append_row(ws, period: str, user_id: int, full_name: str, org_inn: str, org_name: str,
               rating: float, global_rank: int, company_rank: int) -> None:
    ws.append(
        [
            period,
            user_id,
            full_name,
            org_inn,
            org_name,
            rating,
            global_rank,
            company_rank,
        ]
    )


async def build_ratings_excel(
    db_path: str, start_month: str, end_month: str, current_month_label: str
) -> Path:
    wb = Workbook()
    ws_snapshots = wb.active
    ws_snapshots.title = "Снапшоты"
    _write_header(ws_snapshots)

    orgs = await _org_map(db_path)
    monthly_rows = await _monthly_rows(db_path, start_month, end_month)
    for row in monthly_rows:
        org = orgs.get(int(row["org_id"]), {"inn": "", "name": ""})
        _append_row(
            ws_snapshots,
            _month_to_label(row["month"]),
            int(row["tg_user_id"]),
            row["full_name"],
            org["inn"],
            org["name"],
            float(row["total_volume"]),
            int(row["global_rank"]),
            int(row["company_rank"]),
        )

    ws_current = wb.create_sheet("Текущий месяц")
    _write_header(ws_current)
    current_rows = await _current_month_rows(db_path)
    for r in current_rows:
        org = orgs.get(int(r.org_id), {"inn": "", "name": ""})
        _append_row(
            ws_current,
            current_month_label,
            r.tg_user_id,
            r.full_name,
            org["inn"],
            org["name"],
            r.total_volume,
            r.global_rank,
            r.company_rank,
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return Path(tmp.name)
