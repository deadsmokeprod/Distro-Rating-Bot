from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import aiohttp


class OnecClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnecTurnoverRow:
    period: str
    type_operation: str
    nomenclature: str
    volume_goods: float
    volume_partial: float
    seller_inn: str
    seller_name: str
    buyer_inn: str
    buyer_name: str


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace(" ", "").replace(",", ".")
        try:
            return float(normalized)
        except ValueError as exc:
            raise OnecClientError(f"Некорректное число: {value}") from exc
    raise OnecClientError(f"Некорректный тип числа: {type(value)}")


async def fetch_chz_turnover(
    onec_url: str, start_date: str, end_date: str, timeout_seconds: int = 30
) -> List[OnecTurnoverRow]:
    payload = {"startDate": start_date, "endDate": end_date}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(onec_url, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                raise OnecClientError(f"1С ответил {response.status}: {text}")
            data = await response.json()

    if not isinstance(data, dict):
        raise OnecClientError("Неверный формат ответа 1С")
    if not data.get("ok"):
        raise OnecClientError(str(data.get("error", "1С вернул ok=false")))

    rows = data.get("rows")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise OnecClientError("Неверный формат rows в ответе 1С")

    result: List[OnecTurnoverRow] = []
    for item in rows:
        if not isinstance(item, dict):
            raise OnecClientError("Неверный формат строки rows")
        result.append(
            OnecTurnoverRow(
                period=str(item.get("Период", "")).strip(),
                type_operation=str(item.get("ТипОперации", "")).strip(),
                nomenclature=str(item.get("Номенклатура", "")).strip(),
                volume_goods=_to_float(item.get("ОбъемТоваров")),
                volume_partial=_to_float(item.get("ОбъемЧастичнойРеализации")),
                seller_inn=str(item.get("ПродавецИНН", "")).strip(),
                seller_name=str(item.get("ПродавецНаименование", "")).strip(),
                buyer_inn=str(item.get("ПокупательИНН", "")).strip(),
                buyer_name=str(item.get("ПокупательНаименование", "")).strip(),
            )
        )
    return result
