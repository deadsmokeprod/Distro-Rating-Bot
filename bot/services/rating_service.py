from decimal import Decimal
from typing import List, Tuple


def format_decimal(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def build_company_list_view(
    ratings: List[Tuple[str, str, Decimal]],
    user_inn: str,
    anonymize: bool,
) -> List[str]:
    lines = []
    for index, (inn, name, rating) in enumerate(ratings, start=1):
        is_user = inn == user_inn
        if anonymize and not is_user:
            label = f"Компания-конкурент #{index}"
            line = f"{index}. {label}, Рейтинг: {format_decimal(rating)}"
        else:
            line = (
                f"{index}. Наименование компании: {name}, ИНН:{inn}, "
                f"Рейтинг:{format_decimal(rating)}"
            )
        if is_user:
            line = f"<b>{line}</b>"
        lines.append(line)
    return lines
