from __future__ import annotations

import tempfile
from pathlib import Path

from openpyxl import Workbook

from app.db import sqlite


async def build_staff_sales_excel(db_path: str, tg_user_id: int) -> Path:
    rows = await sqlite.list_claimed_sales_for_user_all_time(db_path, tg_user_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Продажи"
    ws.append(
        [
            "Период продажи",
            "Покупатель",
            "Покупатель ИНН",
            "Объем",
            "Номенклатура",
            "Дата фиксации",
            "Статус спора",
        ]
    )
    for row in rows:
        ws.append(
            [
                str(row["period"]),
                str(row["buyer_name"]),
                str(row["buyer_inn"]),
                float(row["volume_goods"]),
                str(row["nomenclature"]),
                str(row["claimed_at"]),
                str(row["dispute_status"]),
            ]
        )
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return Path(tmp.name)
