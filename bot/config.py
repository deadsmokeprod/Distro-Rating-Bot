import json
import os
from dataclasses import dataclass
from typing import Dict, List

from dotenv import load_dotenv

@dataclass
class Config:
    bot_token: str
    db_path: str
    timezone: str
    super_admin_ids: List[int]
    admin_ids: List[int]
    registration_contact_tg_id: int
    bot_support_group_id: int
    erp_http_url: str
    erp_http_user: str
    erp_http_password: str
    erp_timeout_sec: int
    menu_config: Dict[str, List[str]]
    sync_cron: str


DEFAULT_MENU_JSON = {
    "SUPER_ADMIN": [
        "RATING_EXPORT",
        "MY_DISTRIBUTORS",
        "RATING_PERSONAL",
        "RATING_ORG",
        "RATING_ALL",
        "PROFILE",
        "SETTINGS",
        "SUPPORT",
    ],
    "ADMIN": [
        "RATING_EXPORT",
        "MY_DISTRIBUTORS",
        "RATING_PERSONAL",
        "RATING_ORG",
        "RATING_ALL",
        "PROFILE",
        "SETTINGS",
        "SUPPORT",
    ],
    "MINI_ADMIN": [
        "RATING_PERSONAL",
        "RATING_ORG",
        "RATING_ALL",
        "CONFIRM_SALE",
        "PROFILE",
        "SETTINGS",
        "SUPPORT",
    ],
    "USER": [
        "RATING_PERSONAL",
        "RATING_ORG",
        "RATING_ALL",
        "CONFIRM_SALE",
        "PROFILE",
        "SETTINGS",
        "SUPPORT",
    ],
}


def _parse_ids(value: str) -> List[int]:
    if not value:
        return []
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def load_config() -> Config:
    load_dotenv()
    menu_json = os.getenv("MENU_CONFIG_JSON")
    if menu_json:
        menu_config = json.loads(menu_json)
    else:
        menu_config = DEFAULT_MENU_JSON

    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        db_path=os.getenv("DB_PATH", "./data/database.sqlite3"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        super_admin_ids=_parse_ids(os.getenv("SUPER_ADMIN_IDS", "")),
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        registration_contact_tg_id=int(os.getenv("REGISTRATION_CONTACT_TG_ID", "0")),
        bot_support_group_id=int(os.getenv("BOT_SUPPORT_GROUP_ID", "0")),
        erp_http_url=os.getenv("ERP_HTTP_URL", ""),
        erp_http_user=os.getenv("ERP_HTTP_USER", ""),
        erp_http_password=os.getenv("ERP_HTTP_PASSWORD", ""),
        erp_timeout_sec=int(os.getenv("ERP_TIMEOUT_SEC", "30")),
        menu_config=menu_config,
        sync_cron=os.getenv("SYNC_CRON", "0 4 * * 0"),
    )
