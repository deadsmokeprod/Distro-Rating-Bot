from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

def _load_env() -> None:
    load_dotenv(BASE_DIR / ".env")


def _parse_ids(raw: str) -> List[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _parse_menu(raw: str) -> Dict[str, List[str]]:
    if not raw:
        return {}
    return json.loads(raw)


@dataclass
class Config:
    bot_token: str
    db_path: str
    timezone: str
    super_admin_ids: List[int]
    admin_ids: List[int]
    registration_contact_tg_id: int
    support_group_id: int
    erp_http_url: str
    erp_http_user: str
    erp_http_password: str
    erp_timeout_sec: int
    menu_config: Dict[str, List[str]]
    sync_cron: str


_config: Config | None = None


def load_config() -> Config:
    global _config
    if _config is not None:
        return _config
    _load_env()
    _config = Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        db_path=os.getenv("DB_PATH", str(BASE_DIR / "data" / "database.sqlite3")),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        super_admin_ids=_parse_ids(os.getenv("SUPER_ADMIN_IDS", "")),
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        registration_contact_tg_id=int(os.getenv("REGISTRATION_CONTACT_TG_ID", "0")),
        support_group_id=int(os.getenv("BOT_SUPPORT_GROUP_ID", "0")),
        erp_http_url=os.getenv("ERP_HTTP_URL", ""),
        erp_http_user=os.getenv("ERP_HTTP_USER", ""),
        erp_http_password=os.getenv("ERP_HTTP_PASSWORD", ""),
        erp_timeout_sec=int(os.getenv("ERP_TIMEOUT_SEC", "30")),
        menu_config=_parse_menu(os.getenv("MENU_CONFIG_JSON", "{}")),
        sync_cron=os.getenv("SYNC_CRON", "0 4 * * 0"),
    )
    return _config
