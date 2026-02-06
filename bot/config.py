from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


def _parse_super_admin_ids(raw: str | None) -> List[int]:
    if not raw:
        return []
    items = [item.strip() for item in raw.split(",") if item.strip()]
    ids: List[int] = []
    for item in items:
        if item.isdigit():
            ids.append(int(item))
    return ids


@dataclass(frozen=True)
class Config:
    bot_token: str
    timezone: str
    db_path: str
    super_admin_ids: List[int]
    erp_url: str
    erp_username: str
    erp_password: str
    sync_cron: str
    support_group_id: int | None

    @staticmethod
    def load() -> "Config":
        load_dotenv()
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            print("BOT_TOKEN is missing")
            raise SystemExit(1)

        timezone = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
        db_path = os.getenv("DB_PATH", "data/database.sqlite3").strip() or "data/database.sqlite3"
        super_admin_ids = _parse_super_admin_ids(os.getenv("SUPER_ADMIN_IDS"))
        erp_url = os.getenv("ERP_URL", "").strip()
        erp_username = os.getenv("ERP_USERNAME", "").strip()
        erp_password = os.getenv("ERP_PASSWORD", "").strip()
        sync_cron = os.getenv("SYNC_CRON", "*/30 * * * *").strip() or "*/30 * * * *"
        support_group_raw = os.getenv("BOT_SUPPORT_GROUP_ID", "").strip()
        support_group_id = int(support_group_raw) if support_group_raw.lstrip("-").isdigit() else None

        return Config(
            bot_token=bot_token,
            timezone=timezone,
            db_path=db_path,
            super_admin_ids=super_admin_ids,
            erp_url=erp_url,
            erp_username=erp_username,
            erp_password=erp_password,
            sync_cron=sync_cron,
            support_group_id=support_group_id,
        )
