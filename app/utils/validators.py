from __future__ import annotations

import re


def validate_inn(inn: str) -> bool:
    if not inn.isdigit():
        return False
    return len(inn) in (10, 12)


def validate_org_name(name: str) -> bool:
    trimmed = name.strip()
    return 2 <= len(trimmed) <= 200


def validate_card_requisites_line(text: str) -> bool:
    normalized = " ".join(text.strip().split())
    pattern = r"^\d{4}\s\d{4}\s\d{4}\s\d{4}\s+[A-Za-zА-Яа-яЁё\-]+\s+[A-Za-zА-Яа-яЁё\-]+\s+[A-Za-zА-Яа-яЁё\-]+$"
    return bool(re.match(pattern, normalized))
