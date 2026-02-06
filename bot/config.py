from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _parse_super_admin_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError:
            continue
    return ids


@dataclass(slots=True)
class Config:
    bot_token: str
    timezone: str
    db_path: str
    super_admin_ids: list[int]
    erp_url: str
    erp_username: str
    erp_password: str
    sync_cron: str
    bot_support_group_id: int | None

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            print("BOT_TOKEN is missing")
            sys.exit(1)

        timezone = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
        db_path = os.getenv("DB_PATH", "data/database.sqlite3").strip()
        super_admin_ids = _parse_super_admin_ids(os.getenv("SUPER_ADMIN_IDS", ""))
        erp_url = os.getenv("ERP_URL", "").strip()
        erp_username = os.getenv("ERP_USERNAME", "").strip()
        erp_password = os.getenv("ERP_PASSWORD", "").strip()
        sync_cron = os.getenv("SYNC_CRON", "*/30 * * * *").strip() or "*/30 * * * *"
        support_group_raw = os.getenv("BOT_SUPPORT_GROUP_ID", "").strip()
        bot_support_group_id = None
        if support_group_raw:
            try:
                bot_support_group_id = int(support_group_raw)
            except ValueError:
                bot_support_group_id = None

        db_dir = Path(db_path).parent
        if db_dir:
            db_dir.mkdir(parents=True, exist_ok=True)

        Path("logs").mkdir(parents=True, exist_ok=True)

        return cls(
            bot_token=bot_token,
            timezone=timezone,
            db_path=db_path,
            super_admin_ids=super_admin_ids,
            erp_url=erp_url,
            erp_username=erp_username,
            erp_password=erp_password,
            sync_cron=sync_cron,
            bot_support_group_id=bot_support_group_id,
        )
