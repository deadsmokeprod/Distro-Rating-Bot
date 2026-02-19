from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.keyboards.manager import (
    MANAGER_MENU_GOALS_ADMIN,
    MANAGER_MENU_MERGE_ORGS,
    manager_main_menu,
)
from app.keyboards.seller import (
    SELLER_MENU_DISPUTE_MODERATE,
    SELLER_MENU_FIRE_STAFF,
    SELLER_MENU_MY_STAFF,
    seller_main_menu,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


def _flatten_reply_keyboard(reply_markup) -> list[str]:
    rows = getattr(reply_markup, "keyboard", []) or []
    labels: list[str] = []
    for row in rows:
        for button in row:
            labels.append(str(button.text))
    return labels


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def check_seller_role_menus() -> CheckResult:
    seller_labels = _flatten_reply_keyboard(seller_main_menu(role="seller"))
    rop_labels = _flatten_reply_keyboard(seller_main_menu(role="rop"))
    rop_only = {SELLER_MENU_DISPUTE_MODERATE, SELLER_MENU_MY_STAFF, SELLER_MENU_FIRE_STAFF}
    seller_has_rop_only = sorted(lbl for lbl in rop_only if lbl in seller_labels)
    rop_missing = sorted(lbl for lbl in rop_only if lbl not in rop_labels)
    ok = not seller_has_rop_only and not rop_missing
    details = (
        f"seller_has_rop_only={seller_has_rop_only}; "
        f"rop_missing_expected={rop_missing}"
    )
    return CheckResult("Role UI: SELLER vs ROP menus", ok, details)


def check_manager_admin_menus() -> CheckResult:
    manager_labels = _flatten_reply_keyboard(manager_main_menu(is_admin_view=False))
    admin_labels = _flatten_reply_keyboard(manager_main_menu(is_admin_view=True))
    admin_only = {MANAGER_MENU_MERGE_ORGS, MANAGER_MENU_GOALS_ADMIN}
    manager_has_admin_only = sorted(lbl for lbl in admin_only if lbl in manager_labels)
    admin_missing = sorted(lbl for lbl in admin_only if lbl not in admin_labels)
    ok = not manager_has_admin_only and not admin_missing
    details = (
        f"manager_has_admin_only={manager_has_admin_only}; "
        f"admin_missing_expected={admin_missing}"
    )
    return CheckResult("Role UI: MANAGER vs ADMIN menus", ok, details)


def check_support_antispam_flow() -> CheckResult:
    src = _read("app/handlers/start.py")
    required_snippets = [
        "SUPPORT_CONFIRM_DELAY_SEC = 60",
        "class SupportRequestStates(StatesGroup):",
        "support_request_collect_text",
        "support_request_send",
        "support_request_stale",
        "support_confirm_keyboard(",
    ]
    missing = [s for s in required_snippets if s not in src]
    ok = not missing
    return CheckResult(
        "Support anti-spam flow (text/confirm/timer/token)",
        ok,
        f"missing={missing}" if missing else "all required markers present",
    )


def check_inline_single_menu_guards() -> CheckResult:
    seller_src = _read("app/handlers/seller.py")
    manager_src = _read("app/handlers/manager.py")
    required = [
        "router.callback_query.filter(ActiveInlineMenuFilter())",
        "send_single_inline_menu(",
        "mark_inline_menu_active(",
    ]
    missing: list[str] = []
    for token in required:
        if token not in seller_src and token not in manager_src:
            missing.append(token)
    ok = not missing
    return CheckResult(
        "Inline UX: single active menu guards",
        ok,
        f"missing={missing}" if missing else "filters/helpers are wired",
    )


def check_onec_error_handling_markers() -> CheckResult:
    src = _read("app/services/onec_client.py")
    required_patterns = [
        r"if status == 401:",
        r"if status == 403:",
        r"if status == 404:",
        r"if status == 400",
        r"availableOperationTypes",
    ]
    missing = [p for p in required_patterns if not re.search(p, src)]
    ok = not missing
    return CheckResult(
        "1C integration error-path markers",
        ok,
        f"missing={missing}" if missing else "status/error markers present",
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
    ok = not found
    return CheckResult(
        "Logs: no obvious secret leaks",
        ok,
        f"found={found}" if found else "no suspicious token/password markers found",
    )


def run() -> int:
    checks = [
        check_seller_role_menus(),
        check_manager_admin_menus(),
        check_support_antispam_flow(),
        check_inline_single_menu_guards(),
        check_onec_error_handling_markers(),
        check_no_obvious_secret_leaks_in_log(),
    ]
    print("Stage 7 smoke checks")
    print("-" * 60)
    failed = 0
    for c in checks:
        status = "PASS" if c.ok else "FAIL"
        print(f"[{status}] {c.name}")
        print(f"       {c.details}")
        if not c.ok:
            failed += 1
    print("-" * 60)
    print(f"total={len(checks)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
