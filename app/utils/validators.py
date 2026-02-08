from __future__ import annotations


def validate_inn(inn: str) -> bool:
    if not inn.isdigit():
        return False
    return len(inn) in (10, 12)


def validate_org_name(name: str) -> bool:
    trimmed = name.strip()
    return 2 <= len(trimmed) <= 200
