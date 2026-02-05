from decimal import Decimal
from typing import List, Tuple

from openpyxl import Workbook

from bot.services.rating_service import format_decimal


def build_rating_excel(ratings: List[Tuple[str, str, Decimal]], path: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(["Рейтинг", "ИНН", "Наименование организации"])
    for rating, inn, name in ratings:
        ws.append([format_decimal(rating), inn, name])
    wb.save(path)
    return path
