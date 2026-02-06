import json
import ast
import os
from dataclasses import dataclass
from typing import Dict, List

from dotenv import load_dotenv


def _parse_ids(value: str) -> List[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [int(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, (list, tuple)):
            return [int(item) for item in parsed]
    except (ValueError, SyntaxError):
        pass
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _parse_menu(value: str) -> Dict[str, List[str]]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return {}


DEFAULT_MENU_CONFIG = {
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


    @staticmethod
    def load() -> "Config":
        load_dotenv()
        menu_config = _parse_menu(os.getenv("MENU_CONFIG_JSON", "{}"))
        if not menu_config:
            menu_config = DEFAULT_MENU_CONFIG
        else:
            for role, buttons in DEFAULT_MENU_CONFIG.items():
                menu_config.setdefault(role, buttons)
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


BUTTONS = {
    "RATING_EXPORT": "Рейтинг выгрузка",
    "MY_DISTRIBUTORS": "Рейтинг моих дистрибьютеров",
    "RATING_PERSONAL": "Рейтинг в этом месяце — личный",
    "RATING_ORG": "Рейтинг в этом месяце — в компании дистрибьютера",
    "RATING_ALL": "Рейтинг в этом месяце — все компании",
    "CONFIRM_SALE": "Зафиксировать продажу",
    "PROFILE": "Профиль и данные",
    "SETTINGS": "Настройки (админская панель)",
    "SUPPORT": "Создать обращение в техподдержку",
}

ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_MINI_ADMIN = "MINI_ADMIN"
ROLE_USER = "USER"

ALL_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MINI_ADMIN, ROLE_USER}
