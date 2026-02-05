from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from openpyxl import Workbook


def export_ratings(path: Path, rows: Iterable[Tuple[int, str, str]]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ratings"
    ws.append(["Рейтинг", "ИНН", "Наименование организации"])
    for rating, inn, name in rows:
        ws.append([rating, inn, name])
    wb.save(path)
    return path
