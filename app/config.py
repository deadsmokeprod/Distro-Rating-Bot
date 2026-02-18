from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: List[int]
    manager_ids: List[int]
    rop_limit_per_org: int
    support_user_id: int
    support_username: str | None  # без @, для кнопки https://t.me/username
    rules_file_path: str
    onec_url: str | None
    onec_operation_type: str
    onec_username: str | None
    onec_password: str | None
    onec_timeout_seconds: int
    sync_push_enabled: bool
    dispute_push_enabled: bool
    dispute_confirm_delay_sec: int
    merge_confirm_delay_sec: int
    inline_page_size: int
    rating_window_size: int
    supertask_push_new_enabled: bool
    supertask_push_done_enabled: bool
    challenge_growth_pct: int
    challenge_base_volume: float
    bot_launch_date: date
    pool_days: int
    pool_medcoin_per_liter: float
    new_buyer_bonus: float
    avg_window_months: int
    avg_add_pct: int
    avg_ignore_initial_zero_months: int
    max_avg_levels: int
    quiet_hours_start: str
    quiet_hours_end: str
    db_path: str
    log_path: str


_config: Config | None = None


def _parse_ids(raw: str) -> List[int]:
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
    admin_ids = _parse_ids(os.getenv("ADMIN_IDS", ""))
    manager_ids = _parse_ids(os.getenv("MANAGER_IDS", ""))
    rop_limit_per_org = int(os.getenv("ROP_LIMIT_PER_ORG", "2"))
    support_user_id_raw = os.getenv("SUPPORT_USER_ID", "0").strip()
    support_username_raw = (os.getenv("SUPPORT_USERNAME", "") or "").strip().lstrip("@")
    support_username = support_username_raw or None
    rules_file_path = (os.getenv("RULES_FILE_PATH", "./rules.pdf") or "./rules.pdf").strip()
    onec_url_raw = (os.getenv("ONEC_URL", "") or "").strip()
    onec_url = onec_url_raw or None
    onec_operation_type = (os.getenv("ONEC_OPERATION_TYPE", "Передача между УОТ") or "Передача между УОТ").strip()
    onec_username_raw = (os.getenv("ONEC_USERNAME", "") or "").strip()
    onec_username = onec_username_raw or None
    onec_password_raw = (os.getenv("ONEC_PASSWORD", "") or "").strip()
    onec_password = onec_password_raw or None
    onec_timeout_seconds = int(os.getenv("ONEC_TIMEOUT_SECONDS", "60"))
    sync_push_enabled = (os.getenv("SYNC_PUSH_ENABLED", "1").strip() == "1")
    dispute_push_enabled = (os.getenv("DISPUTE_PUSH_ENABLED", "1").strip() == "1")
    dispute_confirm_delay_sec = int(os.getenv("DISPUTE_CONFIRM_DELAY_SEC", "60"))
    merge_confirm_delay_sec = int(os.getenv("MERGE_CONFIRM_DELAY_SEC", "60"))
    inline_page_size = int(os.getenv("INLINE_PAGE_SIZE", "10"))
    rating_window_size = int(os.getenv("RATING_WINDOW_SIZE", "10"))
    supertask_push_new_enabled = (os.getenv("SUPERTASK_PUSH_NEW_ENABLED", "1").strip() == "1")
    supertask_push_done_enabled = (os.getenv("SUPERTASK_PUSH_DONE_ENABLED", "1").strip() == "1")
    challenge_growth_pct = int(os.getenv("CHALLENGE_GROWTH_PCT", "20"))
    challenge_base_volume = float(os.getenv("CHALLENGE_BASE_VOLUME", "10"))
    bot_launch_date_raw = (os.getenv("BOT_LAUNCH_DATE", "2026-02-17") or "2026-02-17").strip()
    pool_days = int(os.getenv("POOL_DAYS", "14"))
    pool_medcoin_per_liter = float(os.getenv("POOL_MEDCOIN_PER_LITER", "1.5"))
    new_buyer_bonus = float(os.getenv("NEW_BUYER_BONUS", "50"))
    avg_window_months = int(os.getenv("AVG_WINDOW_MONTHS", "3"))
    avg_add_pct = int(os.getenv("AVG_ADD_PCT", "10"))
    avg_ignore_initial_zero_months = int(os.getenv("AVG_IGNORE_INITIAL_ZERO_MONTHS", "2"))
    max_avg_levels = int(os.getenv("MAX_AVG_LEVELS", "10"))
    quiet_hours_start = (os.getenv("QUIET_HOURS_START", "19:00") or "19:00").strip()
    quiet_hours_end = (os.getenv("QUIET_HOURS_END", "08:00") or "08:00").strip()
    db_path = os.getenv("DB_PATH", "./data/bot.sqlite3").strip()
    log_path = os.getenv("LOG_PATH", "./logs/bot.log").strip()

    if not bot_token:
        raise ValueError("BOT_TOKEN is required")
    if not support_user_id_raw:
        raise ValueError("SUPPORT_USER_ID is required")

    support_user_id = int(support_user_id_raw)
    try:
        bot_launch_date = datetime.strptime(bot_launch_date_raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("BOT_LAUNCH_DATE must be YYYY-MM-DD") from exc

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    _config = Config(
        bot_token=bot_token,
        admin_ids=admin_ids,
        manager_ids=manager_ids,
        rop_limit_per_org=rop_limit_per_org,
        support_user_id=support_user_id,
        support_username=support_username,
        rules_file_path=rules_file_path,
        onec_url=onec_url,
        onec_operation_type=onec_operation_type,
        onec_username=onec_username,
        onec_password=onec_password,
        onec_timeout_seconds=onec_timeout_seconds,
        sync_push_enabled=sync_push_enabled,
        dispute_push_enabled=dispute_push_enabled,
        dispute_confirm_delay_sec=dispute_confirm_delay_sec,
        merge_confirm_delay_sec=merge_confirm_delay_sec,
        inline_page_size=inline_page_size,
        rating_window_size=rating_window_size,
        supertask_push_new_enabled=supertask_push_new_enabled,
        supertask_push_done_enabled=supertask_push_done_enabled,
        challenge_growth_pct=challenge_growth_pct,
        challenge_base_volume=challenge_base_volume,
        bot_launch_date=bot_launch_date,
        pool_days=pool_days,
        pool_medcoin_per_liter=pool_medcoin_per_liter,
        new_buyer_bonus=new_buyer_bonus,
        avg_window_months=avg_window_months,
        avg_add_pct=avg_add_pct,
        avg_ignore_initial_zero_months=avg_ignore_initial_zero_months,
        max_avg_levels=max_avg_levels,
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
