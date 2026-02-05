import json
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    db_path: str
    timezone: str
    super_admin_ids: set[int]
    admin_ids: set[int]
    registration_contact_tg_id: int
    support_group_id: int
    erp_http_url: str
    erp_http_user: str
    erp_http_password: str
    erp_timeout_sec: int
    menu_config: dict
    sync_cron: str
    logs_path: Path



def _parse_ids(raw: str) -> set[int]:
    if not raw:
        return set()
    return {int(item.strip()) for item in raw.split(",") if item.strip()}



def load_config() -> Config:
    menu_config_raw = os.getenv("MENU_CONFIG_JSON", "{}")
    menu_config = json.loads(menu_config_raw)
    logs_path = Path("logs")
    logs_path.mkdir(parents=True, exist_ok=True)
    return Config(
        bot_token=os.getenv("BOT_TOKEN", ""),
        db_path=os.getenv("DB_PATH", "./data/database.sqlite3"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        super_admin_ids=_parse_ids(os.getenv("SUPER_ADMIN_IDS", "")),
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        registration_contact_tg_id=int(os.getenv("REGISTRATION_CONTACT_TG_ID", "0")),
        support_group_id=int(os.getenv("BOT_SUPPORT_GROUP_ID", "0")),
        erp_http_url=os.getenv("ERP_HTTP_URL", ""),
        erp_http_user=os.getenv("ERP_HTTP_USER", ""),
        erp_http_password=os.getenv("ERP_HTTP_PASSWORD", ""),
        erp_timeout_sec=int(os.getenv("ERP_TIMEOUT_SEC", "30")),
        menu_config=menu_config,
        sync_cron=os.getenv("SYNC_CRON", "0 4 * * 0"),
        logs_path=logs_path,
    )
