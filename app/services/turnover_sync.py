from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.config import Config
from app.db import sqlite
from app.db.sqlite import upsert_chz_turnover
from app.services.onec_client import OnecClientError, OnecTurnoverRow, fetch_chz_turnover

logger = logging.getLogger(__name__)


def current_month_range(today: date) -> tuple[date, date]:
    return today.replace(day=1), today


def last_30_days_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=30), today


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _rows_to_dicts(rows: list[OnecTurnoverRow]) -> list[dict]:
    return [asdict(row) for row in rows]


def _basic_auth_tuple(config: Config) -> tuple[str, str] | None:
    if config.onec_username and config.onec_password:
        return (config.onec_username, config.onec_password)
    return None


@dataclass(frozen=True)
class SyncTurnoverResult:
    fetched_count: int
    upserted_count: int
    inserted_count: int
    affected_seller_inns: list[str]
    affected_company_group_ids: list[int]


async def sync_turnover(
    config: Config,
    start: date,
    end: date,
    operation_type: str | None = None,
) -> SyncTurnoverResult:
    if not config.onec_url:
        raise OnecClientError("ONEC_URL не задан")
    op_type = operation_type if operation_type is not None else config.onec_operation_type
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    rows = await fetch_chz_turnover(
        config.onec_url,
        start_iso,
        end_iso,
        operation_type=op_type,
        timeout_seconds=config.onec_timeout_seconds,
        basic_auth=_basic_auth_tuple(config),
    )
    upsert_result = await upsert_chz_turnover(config.db_path, _rows_to_dicts(rows))
    return SyncTurnoverResult(
        fetched_count=len(rows),
        upserted_count=int(upsert_result["upserted_count"]),
        inserted_count=int(upsert_result["inserted_count"]),
        affected_seller_inns=[str(v) for v in upsert_result["affected_seller_inns"]],
        affected_company_group_ids=[int(v) for v in upsert_result["affected_company_group_ids"]],
    )


async def send_sync_push_if_needed(
    bot: Bot,
    config: Config,
    result: SyncTurnoverResult,
) -> int:
    if not config.sync_push_enabled:
        return 0
    if result.inserted_count <= 0:
        return 0
    if not result.affected_company_group_ids:
        return 0
    placeholders = ",".join("?" for _ in result.affected_company_group_ids)
    rows = await sqlite.fetch_all(
        config.db_path,
        f"""
        SELECT DISTINCT tg_user_id
        FROM users
        WHERE status = 'active'
          AND role IN ('seller', 'rop')
          AND company_group_id IN ({placeholders})
        """,
        tuple(result.affected_company_group_ids),
    )
    sent = 0
    for row in rows:
        tg_user_id = int(row["tg_user_id"])
        try:
            await bot.send_message(
                tg_user_id,
                "Данные обновлены! У вас есть неразобранные продажи.",
            )
            sent += 1
        except Exception:
            logger.exception("Failed to send sync push to %s", tg_user_id)
    return sent
