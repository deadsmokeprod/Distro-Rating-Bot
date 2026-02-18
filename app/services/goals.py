from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Config
from app.db import sqlite


def _moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value[:10]).date()


def _period_key(starts_at: str, ends_at: str) -> str:
    return f"{starts_at[:10]}__{ends_at[:10]}"


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


async def _ensure_pool_state(cfg: Config, company_group_id: int) -> tuple[str, str]:
    current = await sqlite.get_pool_state_for_group(cfg.db_path, company_group_id)
    if current:
        return str(current["started_at"]), str(current["ends_at"])
    created_at = await sqlite.get_company_group_created_at(cfg.db_path, company_group_id)
    if not created_at:
        now_iso = datetime.utcnow().isoformat()
        return now_iso, now_iso
    starts_at = str(created_at)
    ends_dt = datetime.fromisoformat(starts_at) + timedelta(days=max(0, cfg.pool_days))
    ends_at = ends_dt.isoformat()
    await sqlite.upsert_pool_state_for_group(cfg.db_path, company_group_id, starts_at, ends_at)
    return starts_at, ends_at


async def _apply_claim_stage_award(
    cfg: Config,
    claim_row: dict[str, Any],
    stage_code: str,
    target_tg_user_id: int | None,
    target_amount: float,
    comment: str,
) -> None:
    claim_id = int(claim_row["id"])
    state = await sqlite.get_claim_stage_award(cfg.db_path, claim_id, stage_code)
    prev_user_id = int(state["tg_user_id"]) if state and state["tg_user_id"] is not None else None
    prev_amount = float(state["amount"]) if state else 0.0
    if prev_user_id == target_tg_user_id and abs(prev_amount - target_amount) < 1e-9:
        return
    company_group_id = int(claim_row["company_group_id_at_claim"])
    org_id = int(claim_row["org_id_at_claim"])
    if prev_user_id is not None and abs(prev_amount) > 1e-9:
        await sqlite.add_medcoin_ledger_entry(
            cfg.db_path,
            tg_user_id=prev_user_id,
            company_group_id=company_group_id,
            org_id=org_id,
            entry_kind="adjust",
            stage_code=stage_code,
            amount=-prev_amount,
            available_delta=-prev_amount,
            frozen_delta=0,
            related_entity_type="sales_claim",
            related_entity_id=claim_id,
            comment=f"Reverse previous award: {comment}",
        )
    if target_tg_user_id is not None and abs(target_amount) > 1e-9:
        await sqlite.add_medcoin_ledger_entry(
            cfg.db_path,
            tg_user_id=target_tg_user_id,
            company_group_id=company_group_id,
            org_id=org_id,
            entry_kind="earn",
            stage_code=stage_code,
            amount=target_amount,
            available_delta=target_amount,
            frozen_delta=0,
            related_entity_type="sales_claim",
            related_entity_id=claim_id,
            comment=comment,
        )
    await sqlite.set_claim_stage_award(
        cfg.db_path,
        claim_id=claim_id,
        stage_code=stage_code,
        tg_user_id=target_tg_user_id,
        amount=target_amount,
    )


async def _sync_pool_bonus(cfg: Config, claim_row: dict[str, Any]) -> None:
    claim_period = _parse_iso_date(str(claim_row["period"]))
    if claim_period < cfg.bot_launch_date:
        await _apply_claim_stage_award(cfg, claim_row, "pool_bonus", None, 0, "Pool bonus")
        return
    starts_at, ends_at = await _ensure_pool_state(cfg, int(claim_row["company_group_id_at_claim"]))
    pool_start = _parse_iso_date(starts_at)
    pool_end = _parse_iso_date(ends_at)
    in_pool = pool_start <= claim_period <= pool_end
    if not in_pool or str(claim_row["dispute_status"]) == "open":
        await _apply_claim_stage_award(cfg, claim_row, "pool_bonus", None, 0, "Pool bonus")
        return
    amount = float(claim_row["volume_goods"]) * float(cfg.pool_medcoin_per_liter)
    await _apply_claim_stage_award(
        cfg,
        claim_row,
        "pool_bonus",
        int(claim_row["claimed_by_tg_user_id"]),
        amount,
        "Pool bonus by liters",
    )


async def _sync_new_buyer_bonus(cfg: Config, claim_row: dict[str, Any]) -> None:
    buyer_inn = str(claim_row["buyer_inn"])
    company_group_id = int(claim_row["company_group_id_at_claim"])
    prior_exists = await sqlite.has_group_sales_before_period(
        cfg.db_path, company_group_id, buyer_inn, str(claim_row["period"])[:10]
    )
    existing = await sqlite.get_new_buyer_award_by_buyer(cfg.db_path, company_group_id, buyer_inn)
    claim_id = int(claim_row["id"])
    if prior_exists and (not existing or int(existing["claim_id"]) != claim_id):
        await _apply_claim_stage_award(cfg, claim_row, "new_buyer_bonus", None, 0, "New buyer bonus")
        return
    if existing and int(existing["claim_id"]) != claim_id:
        await _apply_claim_stage_award(cfg, claim_row, "new_buyer_bonus", None, 0, "New buyer bonus")
        return
    await sqlite.upsert_new_buyer_award(
        cfg.db_path,
        company_group_id=company_group_id,
        buyer_inn=buyer_inn,
        claim_id=claim_id,
        tg_user_id=int(claim_row["claimed_by_tg_user_id"]),
        reward=float(cfg.new_buyer_bonus),
    )
    if str(claim_row["dispute_status"]) == "open":
        await _apply_claim_stage_award(cfg, claim_row, "new_buyer_bonus", None, 0, "New buyer bonus")
        return
    await _apply_claim_stage_award(
        cfg,
        claim_row,
        "new_buyer_bonus",
        int(claim_row["claimed_by_tg_user_id"]),
        float(cfg.new_buyer_bonus),
        "New buyer bonus",
    )


async def _sync_supertask_bonus(cfg: Config, claim_row: dict[str, Any]) -> int | None:
    tasks = await sqlite.list_supertasks_active_by_buyer_inn(cfg.db_path, str(claim_row["buyer_inn"]))
    claim_id = int(claim_row["id"])
    if not tasks:
        await _apply_claim_stage_award(cfg, claim_row, "supertask_bonus", None, 0, "Supertask bonus")
        return None
    task = dict(tasks[0])
    claimant_id = int(claim_row["claimed_by_tg_user_id"])
    status = "pending_dispute" if str(claim_row["dispute_status"]) == "open" else "pending"
    await sqlite.upsert_supertask_candidate(
        cfg.db_path,
        supertask_id=int(task["id"]),
        claim_id=claim_id,
        tg_user_id=claimant_id,
        status=status,
    )
    if str(claim_row["dispute_status"]) == "open":
        await sqlite.set_supertask_assignment(
            cfg.db_path,
            supertask_id=int(task["id"]),
            status="pending",
            claim_id=claim_id,
            tg_user_id=claimant_id,
        )
        await _apply_claim_stage_award(cfg, claim_row, "supertask_bonus", None, 0, "Supertask bonus")
        return None
    await sqlite.close_supertask_with_winner(
        cfg.db_path, int(task["id"]), claim_id=claim_id, tg_user_id=claimant_id
    )
    await _apply_claim_stage_award(
        cfg,
        claim_row,
        "supertask_bonus",
        claimant_id,
        float(task["reward"]),
        "Supertask completed",
    )
    return int(task["id"])


async def sync_claim_goals(cfg: Config, claim_id: int) -> dict[str, Any]:
    row = await sqlite.get_claim_with_turnover(cfg.db_path, claim_id)
    if not row:
        return {"supertask_completed_id": None}
    claim_row = dict(row)
    await _sync_pool_bonus(cfg, claim_row)
    await _sync_new_buyer_bonus(cfg, claim_row)
    supertask_completed_id = await _sync_supertask_bonus(cfg, claim_row)
    await sync_avg_levels_for_user(cfg, int(claim_row["claimed_by_tg_user_id"]))
    return {"supertask_completed_id": supertask_completed_id}


async def sync_avg_levels_for_user(cfg: Config, tg_user_id: int) -> list[int]:
    levels = [dict(r) for r in await sqlite.list_active_avg_levels_for_user(cfg.db_path, tg_user_id)]
    created_awards: list[int] = []
    for level in levels:
        period_key = _period_key(str(level["starts_at"]), str(level["ends_at"]))
        if await sqlite.has_avg_level_award(cfg.db_path, int(level["id"]), tg_user_id, period_key):
            continue
        liters = await sqlite.get_sum_liters_between(
            cfg.db_path, tg_user_id, str(level["starts_at"]), str(level["ends_at"])
        )
        if liters < float(level["target_liters"]):
            continue
        award_id = await sqlite.create_avg_level_award(
            cfg.db_path,
            avg_level_id=int(level["id"]),
            tg_user_id=tg_user_id,
            period_key=period_key,
            claim_id=None,
            reward=float(level["reward"]),
        )
        user = await sqlite.get_user_by_tg_id(cfg.db_path, tg_user_id)
        if user:
            await sqlite.add_medcoin_ledger_entry(
                cfg.db_path,
                tg_user_id=tg_user_id,
                company_group_id=int(user["company_group_id"]),
                org_id=int(user["org_id"]),
                entry_kind="earn",
                stage_code="avg_level_bonus",
                amount=float(level["reward"]),
                available_delta=float(level["reward"]),
                frozen_delta=0,
                related_entity_type="avg_level",
                related_entity_id=int(level["id"]),
                comment="Avg level period bonus",
            )
        created_awards.append(award_id)
    return created_awards


async def compute_avg_target(cfg: Config, tg_user_id: int) -> float:
    months = max(1, cfg.avg_window_months)
    ignore_zero = max(0, cfg.avg_ignore_initial_zero_months)
    today = _moscow_today()
    values: list[float] = []
    for i in range(1, months + ignore_zero + 3):
        m = today.replace(day=1) - timedelta(days=1)
        for _ in range(i - 1):
            m = m.replace(day=1) - timedelta(days=1)
        month_key = f"{m.year:04d}-{m.month:02d}"
        metrics = await sqlite.get_month_claim_metrics(cfg.db_path, tg_user_id, month_key)
        values.append(float(metrics["liters"]))
    while values and abs(values[0]) < 1e-9 and ignore_zero > 0:
        values.pop(0)
        ignore_zero -= 1
    values = values[:months] if values else [0.0]
    avg = sum(values) / len(values)
    return avg * (1 + cfg.avg_add_pct / 100.0)


async def render_personal_goals_text(cfg: Config, user: dict[str, Any]) -> str:
    tg_user_id = int(user["tg_user_id"])
    company_group_id = int(user["company_group_id"])
    pool_start, pool_end = await _ensure_pool_state(cfg, company_group_id)
    pool_line = f"Бассейн: {pool_start[:10]} — {pool_end[:10]} ({cfg.pool_medcoin_per_liter:g} 🍯/л)"
    avg_target = await compute_avg_target(cfg, tg_user_id)
    supertasks = [dict(r) for r in await sqlite.list_active_supertasks_for_user(cfg.db_path, tg_user_id, company_group_id)]
    supertask_lines = []
    for task in supertasks[:10]:
        supertask_lines.append(
            f"- #{task['id']} INN {task['target_inn']} / награда {_fmt(float(task['reward']))} 🍯 / статус {task['status']}"
        )
    if not supertask_lines:
        supertask_lines = ["- Нет активных сверхзадач"]
    avg_levels = [dict(r) for r in await sqlite.list_active_avg_levels_for_user(cfg.db_path, tg_user_id)]
    avg_lines = []
    for level in avg_levels[:10]:
        liters = await sqlite.get_sum_liters_between(
            cfg.db_path, tg_user_id, str(level["starts_at"]), str(level["ends_at"])
        )
        avg_lines.append(
            f"- Уровень #{level['id']}: цель {float(level['target_liters']):g} л, факт {liters:g} л, награда {_fmt(float(level['reward']))} 🍯"
        )
    if not avg_lines:
        avg_lines = ["- Нет активных уровней"]
    return (
        "Личные цели:\n"
        f"{pool_line}\n"
        f"New buyer бонус: {_fmt(float(cfg.new_buyer_bonus))} 🍯\n"
        f"Среднемесячная базовая цель: {_fmt(avg_target)} л (+{cfg.avg_add_pct}%)\n\n"
        "Сверхзадачи:\n"
        + "\n".join(supertask_lines)
        + "\n\nСреднемесячные уровни:\n"
        + "\n".join(avg_lines)
    )
