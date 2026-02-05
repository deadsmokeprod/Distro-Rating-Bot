from pathlib import Path
from typing import Iterable

from openpyxl import Workbook


def export_rating(filename: Path, rows: Iterable[tuple[int, str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rating"
    ws.append(["Рейтинг", "ИНН", "Наименование организации"])
    for rating, inn, name in rows:
        ws.append([rating, inn, name])
    wb.save(filename)
