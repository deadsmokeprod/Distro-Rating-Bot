from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def check_broadcast_media_and_audit_markers() -> CheckResult:
    src = _read("app/handlers/manager.py")
    required = [
        "copy_message(",
        "_broadcast_content_preview(",
        "content_type",
        "MANAGER_BROADCAST_BY_ORG",
    ]
    missing = [token for token in required if token not in src]
    return CheckResult(
        "BR-07 broadcast media/target/audit markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_manager_help_flow_markers() -> CheckResult:
    src = _read("app/handlers/start.py")
    required = [
        "class ManagerHelpRequestStates(StatesGroup):",
        "manager_help_request_callback",
        "manager_help_collect_text",
        "manager_help_send",
        "manager_help_stale",
    ]
    missing = [token for token in required if token not in src]
    return CheckResult(
        "BR-08 manager-help flow markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_antispam_env_config_markers() -> CheckResult:
    config_src = _read("app/config.py")
    env_src = _read(".env.example")
    required_config = [
        "sale_confirm_limit",
        "dispute_open_limit",
        "merge_execute_limit",
        "sale_confirm_global_cooldown_sec",
        "dispute_open_global_cooldown_sec",
    ]
    required_env = [
        "SALE_CONFIRM_LIMIT=",
        "DISPUTE_OPEN_LIMIT=",
        "MERGE_EXECUTE_LIMIT=",
        "SALE_CONFIRM_GLOBAL_COOLDOWN_SEC=",
        "DISPUTE_OPEN_GLOBAL_COOLDOWN_SEC=",
    ]
    missing = [token for token in required_config if token not in config_src]
    missing.extend([token for token in required_env if token not in env_src])
    return CheckResult(
        "BR-09 anti-spam env/config markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_dispute_result_notifications_markers() -> CheckResult:
    src = _read("app/handlers/seller.py")
    required = [
        "_notify_dispute_resolution_participants(",
        "_dispute_resolution_push_text(",
        "disp_result_notify:",
        "seller_dispute_mod_approve",
        "seller_dispute_mod_reject",
    ]
    missing = [token for token in required if token not in src]
    return CheckResult(
        "BR-10 dispute result notification markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_user_labels_markers() -> CheckResult:
    seller_src = _read("app/handlers/seller.py")
    manager_src = _read("app/handlers/manager.py")
    required = [
        "_person_label(",
        "Пользователь: {profile_label}",
        "Сотрудник: {staff_label}",
    ]
    missing = [token for token in required if token not in seller_src and token not in manager_src]
    return CheckResult(
        "BR-11 user label markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_grouping_markers() -> CheckResult:
    db_src = _read("app/db/sqlite.py")
    seller_src = _read("app/handlers/seller.py")
    required = [
        "sale_dispute_claims",
        "create_sale_dispute_group(",
        "claim_turnover_group_by_inns(",
        "count_unclaimed_turnover_groups_by_inns(",
        "list_claimed_sale_groups_for_dispute(",
        "Позиции в группе:",
    ]
    missing = [token for token in required if token not in db_src and token not in seller_src]
    return CheckResult(
        "BR-12 sales grouping markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_stage7_style_markers() -> CheckResult:
    start_src = _read("app/handlers/start.py")
    seller_src = _read("app/handlers/seller.py")
    required = [
        "Легионер, добро пожаловать в главный лагерь",
        "📜 Выберите раздел Скрижалей легиона",
        "🍯 Казна легионера",
        "⚖️ Арена споров по продажам",
    ]
    missing = [token for token in required if token not in start_src and token not in seller_src]
    return CheckResult(
        "BR-13 main screen/style markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_new_seller_menu_structure_markers() -> CheckResult:
    kb_src = _read("app/keyboards/seller.py")
    handler_src = _read("app/handlers/seller.py")
    required = [
        "SELLER_MENU_DISPUTES",
        "SELLER_MENU_STAFF_COMPANIES",
        "def seller_disputes_menu(",
        "def seller_staff_companies_menu(",
        "seller_disputes_root",
        "seller_staff_companies_root",
    ]
    missing = [token for token in required if token not in kb_src and token not in handler_src]
    return CheckResult(
        "New SELLER/ROP menu structure markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_navigation_history_markers() -> CheckResult:
    nav_src = _read("app/utils/nav_history.py")
    seller_src = _read("app/handlers/seller.py")
    required = [
        "push_history(",
        "pop_history(",
        "clear_history(",
        "NAV_MAIN",
        "seller_back(",
        "seller_sales_back_menu(",
    ]
    missing = [token for token in required if token not in nav_src and token not in seller_src]
    return CheckResult(
        "Back navigation history markers",
        not missing,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_support_no_delay_cooldown_markers() -> CheckResult:
    start_src = _read("app/handlers/start.py")
    cfg_src = _read("app/config.py")
    env_src = _read(".env.example")
    required = [
        "support_send_cooldown_sec",
        "manager_help_send_cooldown_sec",
        "support_send:",
        "manager_help_send:",
    ]
    missing = [token for token in required if token not in start_src and token not in cfg_src]
    has_rate_limit_marker = "is_rate_limited(" in start_src or "acquire_rate_limit(" in start_src
    if not has_rate_limit_marker:
        missing.append("rate limit call marker")
    if "SUPPORT_SEND_COOLDOWN_SEC=" not in env_src:
        missing.append("SUPPORT_SEND_COOLDOWN_SEC=")
    if "MANAGER_HELP_SEND_COOLDOWN_SEC=" not in env_src:
        missing.append("MANAGER_HELP_SEND_COOLDOWN_SEC=")
    if "SUPPORT_CONFIRM_DELAY_SEC" in start_src:
        missing.append("SUPPORT_CONFIRM_DELAY_SEC should be removed from start.py")
    return CheckResult(
        "Support/manager-help: no delay + cooldown markers",
        not missing,
        f"issues={missing}" if missing else "all required markers present",
    )


def check_no_obvious_secret_leaks_in_log() -> CheckResult:
    log_path = ROOT / "logs" / "bot.log"
    if not log_path.exists():
        return CheckResult("Logs: no obvious secret leaks", True, "log file not found, skipped")
    data = log_path.read_text(encoding="utf-8", errors="ignore")
    suspicious = [
        "BOT_TOKEN=",
        "ONEC_PASSWORD=",
        "bot token",
        "onec_password",
    ]
    found = [s for s in suspicious if s.lower() in data.lower()]
    token_like_match = re.search(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b", data)
    if token_like_match:
        found.append("telegram-token-like-pattern")
    return CheckResult(
        "Logs: no obvious secret leaks",
        not found,
        f"found={found}" if found else "no suspicious token/password markers found",
    )


def run() -> int:
    checks = [
        check_broadcast_media_and_audit_markers(),
        check_manager_help_flow_markers(),
        check_antispam_env_config_markers(),
        check_dispute_result_notifications_markers(),
        check_user_labels_markers(),
        check_grouping_markers(),
        check_stage7_style_markers(),
        check_new_seller_menu_structure_markers(),
        check_navigation_history_markers(),
        check_support_no_delay_cooldown_markers(),
        check_no_obvious_secret_leaks_in_log(),
    ]
    print("Stage 4 final smoke checks")
    print("-" * 60)
    failed = 0
    for check in checks:
        status = "PASS" if check.ok else "FAIL"
        print(f"[{status}] {check.name}")
        print(f"       {check.details}")
        if not check.ok:
            failed += 1
    print("-" * 60)
    print(f"total={len(checks)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
