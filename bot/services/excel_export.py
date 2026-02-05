from pathlib import Path
from openpyxl import Workbook


def export_company_ratings(rows: list[tuple[int, str, str]], file_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Рейтинг"
    ws.append(["Рейтинг", "ИНН", "Наименование организации"])
    for rating, inn, name in rows:
        ws.append([rating, inn, name])
    wb.save(file_path)
