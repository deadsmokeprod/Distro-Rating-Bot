from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    manager_ids: List[int]
    support_user_id: int
    support_username: str | None  # без @, для кнопки https://t.me/username
    onec_url: str | None
    onec_operation_type: str
    onec_username: str | None
    onec_password: str | None
    onec_timeout_seconds: int
    challenge_growth_pct: int
    challenge_base_volume: float
    quiet_hours_start: str
    quiet_hours_end: str
    db_path: str
    log_path: str


_config: Config | None = None


def _parse_manager_ids(raw: str) -> List[int]:
    if not raw:
        return []
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    return [int(item) for item in parts]


def load_config() -> Config:
    global _config
    if _config is not None:
        return _config

    # Загружаем .env из каталога проекта (где bot.py), а не из текущей рабочей папки
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    manager_ids = _parse_manager_ids(os.getenv("MANAGER_IDS", ""))
    support_user_id_raw = os.getenv("SUPPORT_USER_ID", "0").strip()
    support_username_raw = (os.getenv("SUPPORT_USERNAME", "") or "").strip().lstrip("@")
    support_username = support_username_raw or None
    onec_url_raw = (os.getenv("ONEC_URL", "") or "").strip()
    onec_url = onec_url_raw or None
    onec_operation_type = (os.getenv("ONEC_OPERATION_TYPE", "Передача между УОТ") or "Передача между УОТ").strip()
    onec_username_raw = (os.getenv("ONEC_USERNAME", "") or "").strip()
    onec_username = onec_username_raw or None
    onec_password_raw = (os.getenv("ONEC_PASSWORD", "") or "").strip()
    onec_password = onec_password_raw or None
    onec_timeout_seconds = int(os.getenv("ONEC_TIMEOUT_SECONDS", "60"))
    challenge_growth_pct = int(os.getenv("CHALLENGE_GROWTH_PCT", "20"))
    challenge_base_volume = float(os.getenv("CHALLENGE_BASE_VOLUME", "10"))
    quiet_hours_start = (os.getenv("QUIET_HOURS_START", "19:00") or "19:00").strip()
    quiet_hours_end = (os.getenv("QUIET_HOURS_END", "08:00") or "08:00").strip()
    db_path = os.getenv("DB_PATH", "./data/bot.sqlite3").strip()
    log_path = os.getenv("LOG_PATH", "./logs/bot.log").strip()

    if not bot_token:
        raise ValueError("BOT_TOKEN is required")
    if not support_user_id_raw:
        raise ValueError("SUPPORT_USER_ID is required")

    support_user_id = int(support_user_id_raw)

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    _config = Config(
        bot_token=bot_token,
        manager_ids=manager_ids,
        support_user_id=support_user_id,
        support_username=support_username,
        onec_url=onec_url,
        onec_operation_type=onec_operation_type,
        onec_username=onec_username,
        onec_password=onec_password,
        onec_timeout_seconds=onec_timeout_seconds,
        challenge_growth_pct=challenge_growth_pct,
        challenge_base_volume=challenge_base_volume,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        db_path=db_path,
        log_path=log_path,
    )
    return _config


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("Config is not loaded")
    return _config
