from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit
import json
import logging

import aiohttp
from aiohttp import BasicAuth

logger = logging.getLogger(__name__)


class OnecClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "ONEC_ERROR",
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.hint = hint


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


_FIELD_ALIASES: Dict[str, tuple[str, ...]] = {
    "period": ("Период", "period", "Period"),
    "type_operation": ("ТипОперации", "type_operation", "operationType"),
    "nomenclature": ("Номенклатура", "nomenclature"),
    "volume_goods": ("ОбъемТоваров", "volume_goods"),
    "volume_partial": ("ОбъемЧастичнойРеализации", "volume_partial"),
    "seller_inn": ("ПродавецИНН", "seller_inn", "sellerInn"),
    "seller_name": ("ПродавецНаименование", "seller_name", "sellerName"),
    "buyer_inn": ("ПокупательИНН", "buyer_inn", "buyerInn"),
    "buyer_name": ("ПокупательНаименование", "buyer_name", "buyerName"),
}


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
            raise OnecClientError(f"Некорректное число: {value}", code="ONEC_INVALID_NUMBER") from exc
    raise OnecClientError(
        f"Некорректный тип числа: {type(value)}",
        code="ONEC_INVALID_NUMBER_TYPE",
    )


def _safe_url_for_logs(onec_url: str) -> str:
    parts = urlsplit(onec_url)
    path = parts.path or "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


def _request_meta(
    onec_url: str,
    start_date: str,
    end_date: str,
    operation_type: str,
    basic_auth: Optional[Tuple[str, str]],
) -> dict[str, Any]:
    auth_mode = "basic" if basic_auth else "anonymous"
    return {
        "url": _safe_url_for_logs(onec_url),
        "start_date": start_date,
        "end_date": end_date,
        "operation_type": operation_type,
        "auth_mode": auth_mode,
        "has_basic_username": bool(basic_auth and basic_auth[0]),
        "has_basic_password": bool(basic_auth and basic_auth[1]),
    }


def _sanitize_response_preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) > limit:
        return compact[:limit] + "..."
    return compact


def _decode_bytes(raw: bytes, charset: str | None = None) -> str:
    encodings = []
    if charset:
        encodings.append(charset)
    encodings.extend(["utf-8", "cp1251", "latin-1"])
    seen: set[str] = set()
    for enc in encodings:
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _loads_json_any_encoding(raw: bytes, charset: str | None = None) -> dict[str, Any] | None:
    text = _decode_bytes(raw, charset=charset)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _http_status_hint(status: int, auth_mode: str) -> str | None:
    if status == 401:
        if auth_mode == "basic":
            return "Проверьте ONEC_USERNAME/ONEC_PASSWORD, права пользователя 1С и режим публикации HTTP-сервиса."
        return "Проверьте режим auth на публикации 1С (анонимный доступ или Basic Auth)."
    if status == 403:
        return "Проверьте права пользователя 1С на вызов HTTP-сервиса и чтение регистра."
    if status == 404:
        return "Проверьте ONEC_URL: путь публикации/endpoint может быть неверным."
    return None


def _non_200_hint(
    status: int,
    auth_mode: str,
    parsed_json: dict[str, Any] | None,
) -> str | None:
    base_hint = _http_status_hint(status, auth_mode)
    if not parsed_json:
        return base_hint
    available_ops = parsed_json.get("availableOperationTypes")
    server_error = str(parsed_json.get("error") or "")
    if status == 400 and isinstance(available_ops, list):
        valid_ops = [str(v).strip() for v in available_ops if str(v).strip()]
        if valid_ops:
            valid_ops_text = ", ".join(valid_ops[:10])
            return (
                f"Проверьте ONEC_OPERATION_TYPE. Доступные типы операции от 1С: {valid_ops_text}"
            )
    if (
        status == 400
        and "ТипОперации не найден" in server_error
        and isinstance(available_ops, list)
        and not available_ops
    ):
        return (
            "В 1С не найдено ни одного доступного значения ТипОперации для этого пользователя. "
            "Чаще всего это означает, что за выбранный период в базе 1С нет данных по этому типу операции. "
            "Также проверьте права пользователя API и справочник/перечисление типов операций."
        )
    return base_hint


def _pick(item: dict[str, Any], field: str) -> Any:
    keys = _FIELD_ALIASES[field]
    for key in keys:
        if key in item:
            return item.get(key)
    return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


async def fetch_chz_turnover(
    onec_url: str,
    start_date: str,
    end_date: str,
    operation_type: str,
    timeout_seconds: int = 60,
    basic_auth: Optional[Tuple[str, str]] = None,
) -> List[OnecTurnoverRow]:
    # 1С может ожидать латинский ключ (operationType) или русский (ТипОперации) — передаём оба
    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "operationType": operation_type,
        "ТипОперации": operation_type,
    }
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    auth = BasicAuth(basic_auth[0], basic_auth[1]) if basic_auth else None
    meta = _request_meta(onec_url, start_date, end_date, operation_type, basic_auth)
    logger.info(
        "1C request started: url=%s period=%s..%s operation_type=%s auth_mode=%s",
        meta["url"],
        meta["start_date"],
        meta["end_date"],
        meta["operation_type"],
        meta["auth_mode"],
    )
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(onec_url, json=payload, auth=auth) as response:
                response_bytes = await response.read()
                response_text = _decode_bytes(response_bytes, charset=response.charset)
                if response.status != 200:
                    parsed_json = _loads_json_any_encoding(
                        response_bytes, charset=response.charset
                    )
                    hint = _non_200_hint(
                        response.status, str(meta["auth_mode"]), parsed_json
                    )
                    server_error = None
                    if parsed_json and parsed_json.get("error") is not None:
                        server_error = str(parsed_json.get("error"))
                    preview = _sanitize_response_preview(response_text)
                    logger.warning(
                        "1C request failed: status=%s url=%s auth_mode=%s body_preview=%s",
                        response.status,
                        meta["url"],
                        meta["auth_mode"],
                        preview,
                    )
                    message = f"1С ответил {response.status}"
                    if server_error:
                        message += f": {server_error}"
                    raise OnecClientError(
                        message,
                        status_code=response.status,
                        code=f"ONEC_HTTP_{response.status}",
                        hint=hint,
                    )
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "1C response is not valid JSON: url=%s preview=%s",
                        meta["url"],
                        _sanitize_response_preview(response_text),
                    )
                    raise OnecClientError(
                        "1С вернул некорректный JSON",
                        code="ONEC_INVALID_JSON",
                        hint="Проверьте формат ответа HTTP-сервиса 1С (ожидается JSON c ok/rows).",
                    ) from exc
    except asyncio.TimeoutError as exc:
        logger.warning("1C request timeout: url=%s timeout=%ss", meta["url"], timeout_seconds)
        raise OnecClientError(
            f"Таймаут запроса к 1С ({timeout_seconds}с)",
            code="ONEC_TIMEOUT",
            hint="Проверьте доступность endpoint и увеличьте ONEC_TIMEOUT_SECONDS при необходимости.",
        ) from exc
    except aiohttp.ClientError as exc:
        logger.warning("1C transport error: url=%s error=%s", meta["url"], str(exc))
        raise OnecClientError(
            "Сетевая ошибка при обращении к 1С",
            code="ONEC_TRANSPORT_ERROR",
            hint="Проверьте сеть, ONEC_URL и доступность публикации 1С.",
        ) from exc

    if not isinstance(data, dict):
        raise OnecClientError(
            "Неверный формат ответа 1С",
            code="ONEC_INVALID_RESPONSE_TYPE",
        )
    if not data.get("ok"):
        raise OnecClientError(
            str(data.get("error", "1С вернул ok=false")),
            code="ONEC_OK_FALSE",
        )

    rows = data.get("rows")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise OnecClientError(
            "Неверный формат rows в ответе 1С",
            code="ONEC_INVALID_ROWS_TYPE",
        )

    result: List[OnecTurnoverRow] = []
    for idx, item in enumerate(rows):
        if not isinstance(item, dict):
            raise OnecClientError(
                f"Неверный формат строки rows[{idx}]",
                code="ONEC_INVALID_ROW",
            )
        period = _to_text(_pick(item, "period"))
        type_operation = _to_text(_pick(item, "type_operation"))
        nomenclature = _to_text(_pick(item, "nomenclature"))
        seller_inn = _to_text(_pick(item, "seller_inn"))
        buyer_inn = _to_text(_pick(item, "buyer_inn"))
        if not period or not seller_inn or not buyer_inn:
            raise OnecClientError(
                f"Отсутствуют обязательные поля в rows[{idx}]",
                code="ONEC_ROW_MISSING_REQUIRED_FIELDS",
                hint="Проверьте контракт полей 1С -> chz_turnover (Период/ПродавецИНН/ПокупательИНН).",
            )
        result.append(
            OnecTurnoverRow(
                period=period,
                type_operation=type_operation or operation_type,
                nomenclature=nomenclature,
                volume_goods=_to_float(_pick(item, "volume_goods")),
                volume_partial=_to_float(_pick(item, "volume_partial")),
                seller_inn=seller_inn,
                seller_name=_to_text(_pick(item, "seller_name")),
                buyer_inn=buyer_inn,
                buyer_name=_to_text(_pick(item, "buyer_name")),
            )
        )
    logger.info(
        "1C request completed: url=%s rows=%s period=%s..%s operation_type=%s",
        meta["url"],
        len(result),
        meta["start_date"],
        meta["end_date"],
        meta["operation_type"],
    )
    return result
