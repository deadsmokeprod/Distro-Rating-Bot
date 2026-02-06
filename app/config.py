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

    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    manager_ids = _parse_manager_ids(os.getenv("MANAGER_IDS", ""))
    support_user_id_raw = os.getenv("SUPPORT_USER_ID", "0").strip()
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
        db_path=db_path,
        log_path=log_path,
    )
    return _config


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("Config is not loaded")
    return _config
