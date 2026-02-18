from __future__ import annotations

import json
import os
import base64
import hashlib
import hmac
import secrets
from typing import Any, Dict, List, Optional

import aiosqlite

from app.utils.time import now_utc_iso

_SENSITIVE_PREFIX = "enc:v1:"


def _sensitive_secret() -> str:
    # Prefer explicit key; fallback to BOT_TOKEN to preserve compatibility.
    return (os.getenv("DATA_CIPHER_KEY", "") or os.getenv("BOT_TOKEN", "")).strip()


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    counter = 0
    offset = 0
    while offset < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        take = min(len(block), len(data) - offset)
        for i in range(take):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += take
        counter += 1
    return bytes(out)


def _encrypt_sensitive(value: str) -> str:
    if not value:
        return value
    secret = _sensitive_secret()
    if not secret:
        return value
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    nonce = secrets.token_bytes(16)
    plain = value.encode("utf-8")
    cipher = _xor_stream(plain, key, nonce)
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    token = base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")
    return f"{_SENSITIVE_PREFIX}{token}"


def _decrypt_sensitive(value: str) -> str:
    if not value or not value.startswith(_SENSITIVE_PREFIX):
        return value
    secret = _sensitive_secret()
    if not secret:
        return value
    raw_b64 = value[len(_SENSITIVE_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
    except Exception:
        return value
    if len(raw) < 33:  # nonce(16) + tag(16) + >=1 byte payload
        return value
    nonce = raw[:16]
    tag = raw[-16:]
    cipher = raw[16:-16]
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    expected_tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected_tag):
        return value
    try:
        plain = _xor_stream(cipher, key, nonce).decode("utf-8")
    except Exception:
        return value
    return plain


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS company_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_by_manager_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_group_id INTEGER NOT NULL,
                inn TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                seller_password_hash TEXT NOT NULL,
                rop_password_hash TEXT NOT NULL,
                created_by_manager_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                seller_password_rotated_at TEXT,
                rop_password_rotated_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                merged_into_org_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS org_inns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_group_id INTEGER NOT NULL,
                org_id INTEGER NOT NULL,
                inn TEXT NOT NULL,
                active_from TEXT NOT NULL,
                active_to TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(org_id, inn)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_user_id INTEGER PRIMARY KEY,
                org_id INTEGER NOT NULL,
                company_group_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                nickname TEXT NOT NULL DEFAULT '',
                registered_at TEXT NOT NULL,
                last_seen_at TEXT,
                full_name TEXT,
                fired_at TEXT,
                fired_by_tg_user_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                actor_tg_user_id INTEGER,
                actor_role TEXT,
                action TEXT NOT NULL,
                payload_json TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chz_turnover (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                type_operation TEXT NOT NULL,
                nomenclature TEXT NOT NULL,
                volume_goods REAL NOT NULL,
                volume_partial REAL NOT NULL,
                seller_inn TEXT NOT NULL,
                seller_name TEXT NOT NULL,
                buyer_inn TEXT NOT NULL,
                buyer_name TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (
                    period,
                    type_operation,
                    nomenclature,
                    seller_inn,
                    seller_name,
                    buyer_inn,
                    buyer_name
                )
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turnover_id INTEGER NOT NULL UNIQUE,
                claimed_by_tg_user_id INTEGER NOT NULL,
                claimed_at TEXT NOT NULL,
                company_group_id_at_claim INTEGER NOT NULL,
                org_id_at_claim INTEGER NOT NULL,
                dispute_status TEXT NOT NULL DEFAULT 'none',
                dispute_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sale_disputes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id INTEGER NOT NULL,
                turnover_id INTEGER NOT NULL,
                company_group_id INTEGER NOT NULL,
                org_id INTEGER NOT NULL,
                initiator_tg_user_id INTEGER NOT NULL,
                claimed_by_tg_user_id INTEGER NOT NULL,
                moderator_tg_user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT,
                canceled_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings_all_time (
                tg_user_id INTEGER PRIMARY KEY,
                org_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                total_volume REAL NOT NULL,
                global_rank INTEGER NOT NULL,
                company_rank INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings_monthly (
                month TEXT NOT NULL,
                tg_user_id INTEGER NOT NULL,
                org_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                total_volume REAL NOT NULL,
                global_rank INTEGER NOT NULL,
                company_rank INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (month, tg_user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS challenges_biweekly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                target_volume REAL NOT NULL,
                progress_volume REAL NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE (tg_user_id, period_start, period_end)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                context_json TEXT,
                scheduled_at TEXT,
                sent_at TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS requisites_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS medcoin_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                company_group_id INTEGER NOT NULL,
                org_id INTEGER NOT NULL,
                entry_kind TEXT NOT NULL,
                stage_code TEXT NOT NULL,
                amount REAL NOT NULL,
                available_delta REAL NOT NULL DEFAULT 0,
                frozen_delta REAL NOT NULL DEFAULT 0,
                related_entity_type TEXT,
                related_entity_id INTEGER,
                comment TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                company_group_id INTEGER NOT NULL,
                org_id INTEGER NOT NULL,
                requisites_text TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                manager_tg_user_id INTEGER NOT NULL,
                requested_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pool_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_group_id INTEGER NOT NULL UNIQUE,
                started_at TEXT NOT NULL,
                ends_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS supertasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region INTEGER NOT NULL,
                target_inn TEXT NOT NULL,
                reward REAL NOT NULL,
                status TEXT NOT NULL,
                created_by_tg_user_id INTEGER NOT NULL,
                assigned_claim_id INTEGER,
                assigned_tg_user_id INTEGER,
                completed_claim_id INTEGER,
                completed_tg_user_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS supertask_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supertask_id INTEGER NOT NULL,
                claim_id INTEGER NOT NULL,
                tg_user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (supertask_id, claim_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS new_buyer_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_group_id INTEGER NOT NULL,
                buyer_inn TEXT NOT NULL,
                claim_id INTEGER NOT NULL UNIQUE,
                tg_user_id INTEGER NOT NULL,
                reward REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (company_group_id, buyer_inn)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS avg_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                target_liters REAL NOT NULL,
                reward REAL NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by_tg_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS avg_levels_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                avg_level_id INTEGER NOT NULL,
                tg_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT,
                created_by_tg_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS avg_level_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                avg_level_id INTEGER NOT NULL,
                tg_user_id INTEGER NOT NULL,
                period_key TEXT NOT NULL,
                claim_id INTEGER,
                reward REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (avg_level_id, tg_user_id, period_key)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS claim_stage_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id INTEGER NOT NULL,
                stage_code TEXT NOT NULL,
                tg_user_id INTEGER,
                amount REAL NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (claim_id, stage_code)
            )
            """
        )

        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_company_group_id ON users(company_group_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_status_role ON users(status, role)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_group_nickname_active ON users(company_group_id, nickname) WHERE status = 'active'"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orgs_created_by ON organizations(created_by_manager_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orgs_company_group_id ON organizations(company_group_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_org_inns_inn_active ON org_inns(inn, is_active)"
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chz_turnover_period
            ON chz_turnover(period)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sales_claims_turnover
            ON sales_claims(turnover_id)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sales_claims_group_org
            ON sales_claims(company_group_id_at_claim, org_id_at_claim)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sales_claims_dispute
            ON sales_claims(dispute_status, dispute_id)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sale_disputes_group_status
            ON sale_disputes(company_group_id, status)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sale_disputes_initiator
            ON sale_disputes(initiator_tg_user_id, status)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sale_disputes_claimed_by
            ON sale_disputes(claimed_by_tg_user_id, status)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ratings_monthly_month
            ON ratings_monthly(month)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_challenges_biweekly_user_period
            ON challenges_biweekly(tg_user_id, period_start, period_end)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_user_kind
            ON notifications(tg_user_id, kind)
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_requisites_history_tg_user_id ON requisites_history(tg_user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_medcoin_ledger_user_created ON medcoin_ledger(tg_user_id, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_medcoin_ledger_stage_entity ON medcoin_ledger(stage_code, related_entity_type, related_entity_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user_status ON withdrawal_requests(tg_user_id, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_manager_time ON withdrawal_requests(manager_tg_user_id, requested_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_supertasks_status_target ON supertasks(status, target_inn)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_supertask_candidates_task_status ON supertask_candidates(supertask_id, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_new_buyer_awards_group_inn ON new_buyer_awards(company_group_id, buyer_inn)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_avg_levels_user_active ON avg_levels(tg_user_id, is_active, starts_at, ends_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_avg_level_awards_user_period ON avg_level_awards(tg_user_id, period_key)"
        )
        await db.commit()


async def fetch_one(db_path: str, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            return await cursor.fetchone()


async def fetch_all(db_path: str, query: str, params: tuple = ()) -> List[aiosqlite.Row]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()


async def execute(db_path: str, query: str, params: tuple = ()) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(query, params)
        await db.commit()


async def log_audit(
    db_path: str,
    actor_tg_user_id: int | None,
    actor_role: str | None,
    action: str,
    payload: Dict[str, Any] | None = None,
) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    await execute(
        db_path,
        """
        INSERT INTO audit_log (created_at, actor_tg_user_id, actor_role, action, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now_utc_iso(), actor_tg_user_id, actor_role, action, payload_json),
    )


async def get_org_by_inn(db_path: str, inn: str) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT o.*
        FROM organizations o
        JOIN org_inns oi ON oi.org_id = o.id
        WHERE oi.inn = ?
          AND oi.is_active = 1
          AND o.is_active = 1
        LIMIT 1
        """,
        (inn,),
    )


async def get_org_by_id(db_path: str, org_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(db_path, "SELECT * FROM organizations WHERE id = ?", (org_id,))


async def list_org_inns_by_group(db_path: str, company_group_id: int) -> List[str]:
    rows = await fetch_all(
        db_path,
        """
        SELECT inn
        FROM org_inns
        WHERE company_group_id = ? AND is_active = 1
        ORDER BY inn
        """,
        (company_group_id,),
    )
    return [str(r["inn"]) for r in rows]


async def create_org(
    db_path: str,
    inn: str,
    name: str,
    seller_password_hash: str,
    rop_password_hash: str,
    created_by_manager_id: int,
) -> int:
    created_at = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        group_cur = await db.execute(
            """
            INSERT INTO company_groups (title, created_by_manager_id, created_at)
            VALUES (?, ?, ?)
            """,
            (name, created_by_manager_id, created_at),
        )
        company_group_id = group_cur.lastrowid
        org_cur = await db.execute(
            """
            INSERT INTO organizations (
                company_group_id,
                inn,
                name,
                seller_password_hash,
                rop_password_hash,
                created_by_manager_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_group_id,
                inn,
                name,
                seller_password_hash,
                rop_password_hash,
                created_by_manager_id,
                created_at,
            ),
        )
        org_id = org_cur.lastrowid
        await db.execute(
            """
            INSERT INTO org_inns (company_group_id, org_id, inn, active_from, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (company_group_id, org_id, inn, created_at),
        )
        await db.commit()
        return org_id


async def list_active_org_inns(db_path: str, org_id: int) -> List[str]:
    rows = await fetch_all(
        db_path,
        """
        SELECT inn
        FROM org_inns
        WHERE org_id = ? AND is_active = 1
        ORDER BY active_from DESC, id DESC
        """,
        (org_id,),
    )
    return [str(r["inn"]) for r in rows]


async def is_active_inn_for_org(db_path: str, org_id: int, inn: str) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT 1 AS ok
        FROM org_inns
        WHERE org_id = ? AND inn = ? AND is_active = 1
        LIMIT 1
        """,
        (org_id, inn),
    )
    return row is not None


async def rotate_org_inn(
    db_path: str,
    org_id: int,
    old_inn: str,
    new_inn: str,
) -> bool:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        org_cur = await db.execute(
            "SELECT id, company_group_id FROM organizations WHERE id = ? AND is_active = 1",
            (org_id,),
        )
        org_row = await org_cur.fetchone()
        if not org_row:
            return False

        old_cur = await db.execute(
            """
            SELECT id
            FROM org_inns
            WHERE org_id = ? AND inn = ? AND is_active = 1
            LIMIT 1
            """,
            (org_id, old_inn),
        )
        old_row = await old_cur.fetchone()
        if not old_row:
            return False

        conflict_cur = await db.execute(
            """
            SELECT oi.id
            FROM org_inns oi
            JOIN organizations o ON o.id = oi.org_id
            WHERE oi.inn = ?
              AND oi.is_active = 1
              AND o.is_active = 1
              AND oi.org_id <> ?
            LIMIT 1
            """,
            (new_inn, org_id),
        )
        conflict = await conflict_cur.fetchone()
        if conflict:
            return False

        await db.execute(
            """
            UPDATE org_inns
            SET is_active = 0, active_to = ?
            WHERE org_id = ? AND inn = ? AND is_active = 1
            """,
            (now_iso, org_id, old_inn),
        )

        existing_new_cur = await db.execute(
            "SELECT id FROM org_inns WHERE org_id = ? AND inn = ? LIMIT 1",
            (org_id, new_inn),
        )
        existing_new = await existing_new_cur.fetchone()
        if existing_new:
            await db.execute(
                """
                UPDATE org_inns
                SET company_group_id = ?,
                    is_active = 1,
                    active_from = ?,
                    active_to = NULL
                WHERE id = ?
                """,
                (int(org_row["company_group_id"]), now_iso, int(existing_new["id"])),
            )
        else:
            await db.execute(
                """
                INSERT INTO org_inns (company_group_id, org_id, inn, active_from, active_to, is_active)
                VALUES (?, ?, ?, ?, NULL, 1)
                """,
                (int(org_row["company_group_id"]), org_id, new_inn, now_iso),
            )

        await db.execute(
            "UPDATE organizations SET inn = ? WHERE id = ?",
            (new_inn, org_id),
        )
        await db.commit()
    return True


async def merge_organizations(
    db_path: str,
    master_org_id: int,
    joined_org_ids: list[int],
) -> bool:
    target_ids = sorted({int(org_id) for org_id in joined_org_ids if int(org_id) != master_org_id})
    if not target_ids:
        return False
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        master_cur = await db.execute(
            "SELECT id, company_group_id, is_active FROM organizations WHERE id = ?",
            (master_org_id,),
        )
        master = await master_cur.fetchone()
        if not master or int(master["is_active"]) != 1:
            return False
        master_group_id = int(master["company_group_id"])

        placeholders = ",".join("?" for _ in target_ids)
        joined_rows = await db.execute(
            f"""
            SELECT id, company_group_id, is_active
            FROM organizations
            WHERE id IN ({placeholders})
            """,
            tuple(target_ids),
        )
        joined_orgs = await joined_rows.fetchall()
        if len(joined_orgs) != len(target_ids):
            return False

        # Переносим ИНН в мастер-организацию/группу, избегая дублей (UNIQUE(org_id, inn)).
        for joined_org in joined_orgs:
            joined_org_id = int(joined_org["id"])
            inns_cur = await db.execute(
                """
                SELECT id, inn, active_from, active_to, is_active
                FROM org_inns
                WHERE org_id = ?
                ORDER BY id ASC
                """,
                (joined_org_id,),
            )
            inns = await inns_cur.fetchall()
            for inn_row in inns:
                inn = str(inn_row["inn"])
                existing_cur = await db.execute(
                    """
                    SELECT id, active_from, active_to, is_active
                    FROM org_inns
                    WHERE org_id = ? AND inn = ?
                    LIMIT 1
                    """,
                    (master_org_id, inn),
                )
                existing = await existing_cur.fetchone()
                if not existing:
                    await db.execute(
                        """
                        UPDATE org_inns
                        SET company_group_id = ?, org_id = ?
                        WHERE id = ?
                        """,
                        (master_group_id, master_org_id, int(inn_row["id"])),
                    )
                    continue

                existing_active_from = str(existing["active_from"])
                row_active_from = str(inn_row["active_from"])
                merged_active_from = (
                    existing_active_from
                    if existing_active_from <= row_active_from
                    else row_active_from
                )
                merged_is_active = 1 if int(existing["is_active"]) == 1 or int(inn_row["is_active"]) == 1 else 0
                if merged_is_active == 1:
                    merged_active_to = None
                else:
                    times = [v for v in [existing["active_to"], inn_row["active_to"]] if v is not None]
                    merged_active_to = max(str(v) for v in times) if times else None
                await db.execute(
                    """
                    UPDATE org_inns
                    SET company_group_id = ?,
                        active_from = ?,
                        active_to = ?,
                        is_active = ?
                    WHERE id = ?
                    """,
                    (master_group_id, merged_active_from, merged_active_to, merged_is_active, int(existing["id"])),
                )
                await db.execute("DELETE FROM org_inns WHERE id = ?", (int(inn_row["id"]),))

            await db.execute(
                """
                UPDATE users
                SET company_group_id = ?, org_id = ?
                WHERE org_id = ?
                """,
                (master_group_id, master_org_id, joined_org_id),
            )
            await db.execute(
                """
                UPDATE organizations
                SET company_group_id = ?, is_active = 0, merged_into_org_id = ?
                WHERE id = ?
                """,
                (master_group_id, master_org_id, joined_org_id),
            )

        # Поддерживаем корректный is_active у групп: группа без активных организаций -> неактивна.
        group_rows = await db.execute("SELECT id FROM company_groups")
        groups = await group_rows.fetchall()
        for group_row in groups:
            group_id = int(group_row["id"])
            active_cur = await db.execute(
                "SELECT 1 AS ok FROM organizations WHERE company_group_id = ? AND is_active = 1 LIMIT 1",
                (group_id,),
            )
            has_active = await active_cur.fetchone()
            await db.execute(
                "UPDATE company_groups SET is_active = ? WHERE id = ?",
                (1 if has_active else 0, group_id),
            )

        await db.commit()
    return True


async def update_org_password(
    db_path: str, org_id: int, role: str, password_hash: str
) -> None:
    if role == "rop":
        await execute(
            db_path,
            "UPDATE organizations SET rop_password_hash = ?, rop_password_rotated_at = ? WHERE id = ?",
            (password_hash, now_utc_iso(), org_id),
        )
    else:
        await execute(
            db_path,
            "UPDATE organizations SET seller_password_hash = ?, seller_password_rotated_at = ? WHERE id = ?",
            (password_hash, now_utc_iso(), org_id),
        )


async def list_orgs_by_manager(
    db_path: str, manager_id: int, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT * FROM organizations
        WHERE created_by_manager_id = ? AND is_active = 1
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (manager_id, limit, offset),
    )


async def count_orgs_by_manager(db_path: str, manager_id: int) -> int:
    row = await fetch_one(
        db_path,
        "SELECT COUNT(*) AS cnt FROM organizations WHERE created_by_manager_id = ? AND is_active = 1",
        (manager_id,),
    )
    return int(row["cnt"]) if row else 0


async def count_orgs(db_path: str) -> int:
    row = await fetch_one(
        db_path,
        "SELECT COUNT(*) AS cnt FROM organizations WHERE is_active = 1",
    )
    return int(row["cnt"]) if row else 0


async def list_orgs(db_path: str, limit: int, offset: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT * FROM organizations
        WHERE is_active = 1
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )


async def count_sellers_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM users
        WHERE org_id = ? AND role = 'seller' AND status = 'active'
        """,
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def list_sellers_by_org(
    db_path: str, org_id: int, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, registered_at, full_name, nickname
        FROM users
        WHERE org_id = ? AND role = 'seller' AND status = 'active'
        ORDER BY registered_at DESC
        LIMIT ? OFFSET ?
        """,
        (org_id, limit, offset),
    )


async def count_fired_sellers_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM users
        WHERE org_id = ? AND role = 'seller' AND status = 'fired'
        """,
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def list_fired_sellers_by_org(
    db_path: str, org_id: int, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, full_name, nickname, fired_at
        FROM users
        WHERE org_id = ? AND role = 'seller' AND status = 'fired'
        ORDER BY fired_at DESC
        LIMIT ? OFFSET ?
        """,
        (org_id, limit, offset),
    )


async def count_active_rops_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM users
        WHERE org_id = ? AND role = 'rop' AND status = 'active'
        """,
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def list_active_rops_by_org(db_path: str, org_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, full_name, nickname, registered_at
        FROM users
        WHERE org_id = ? AND role = 'rop' AND status = 'active'
        ORDER BY registered_at DESC
        """,
        (org_id,),
    )


async def list_active_rops_by_group(db_path: str, company_group_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, full_name, nickname, registered_at, org_id
        FROM users
        WHERE company_group_id = ? AND role = 'rop' AND status = 'active'
        ORDER BY registered_at DESC
        """,
        (company_group_id,),
    )


async def count_fired_rops_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM users
        WHERE org_id = ? AND role = 'rop' AND status = 'fired'
        """,
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def list_fired_rops_by_org(db_path: str, org_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, full_name, nickname, fired_at
        FROM users
        WHERE org_id = ? AND role = 'rop' AND status = 'fired'
        ORDER BY fired_at DESC
        """,
        (org_id,),
    )


async def list_all_seller_ids(db_path: str) -> List[int]:
    rows = await fetch_all(
        db_path,
        "SELECT tg_user_id FROM users WHERE role IN ('seller','rop') AND status = 'active'",
    )
    return [int(r["tg_user_id"]) for r in rows]


async def list_seller_ids_by_manager(db_path: str, manager_id: int) -> List[int]:
    rows = await fetch_all(
        db_path,
        """
        SELECT u.tg_user_id
        FROM users u
        JOIN organizations o ON o.id = u.org_id
        WHERE u.role IN ('seller','rop') AND u.status = 'active' AND o.created_by_manager_id = ?
        """,
        (manager_id,),
    )
    return [int(r["tg_user_id"]) for r in rows]


async def get_user_by_tg_id(db_path: str, tg_user_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(db_path, "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,))


async def create_user(
    db_path: str,
    tg_user_id: int,
    org_id: int,
    company_group_id: int,
    role: str,
    nickname: str,
    status: str,
    registered_at: str,
    last_seen_at: str,
    full_name: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (
                tg_user_id,
                org_id,
                company_group_id,
                role,
                status,
                nickname,
                registered_at,
                last_seen_at,
                full_name,
                fired_at,
                fired_by_tg_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(tg_user_id)
            DO UPDATE SET
                org_id = excluded.org_id,
                company_group_id = excluded.company_group_id,
                role = CASE
                    WHEN users.status = 'fired' THEN excluded.role
                    ELSE users.role
                END,
                status = excluded.status,
                nickname = excluded.nickname,
                registered_at = excluded.registered_at,
                last_seen_at = excluded.last_seen_at,
                full_name = excluded.full_name,
                fired_at = NULL,
                fired_by_tg_user_id = NULL
            """,
            (
                tg_user_id,
                org_id,
                company_group_id,
                role,
                status,
                nickname,
                registered_at,
                last_seen_at,
                full_name,
            ),
        )
        await db.commit()


async def update_last_seen(db_path: str, tg_user_id: int) -> None:
    await execute(
        db_path,
        "UPDATE users SET last_seen_at = ? WHERE tg_user_id = ?",
        (now_utc_iso(), tg_user_id),
    )


async def is_nickname_taken(db_path: str, company_group_id: int, nickname: str) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT 1 AS ok
        FROM users
        WHERE company_group_id = ?
          AND lower(nickname) = lower(?)
          AND status = 'active'
        LIMIT 1
        """,
        (company_group_id, nickname),
    )
    return row is not None


async def has_active_registration_in_other_org(
    db_path: str, tg_user_id: int, org_id: int
) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT 1 AS ok
        FROM users
        WHERE tg_user_id = ?
          AND status = 'active'
          AND org_id <> ?
        LIMIT 1
        """,
        (tg_user_id, org_id),
    )
    return row is not None


async def fire_user(
    db_path: str,
    tg_user_id: int,
    expected_role: str,
    fired_by_tg_user_id: int,
) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT tg_user_id
        FROM users
        WHERE tg_user_id = ? AND role = ? AND status = 'active'
        """,
        (tg_user_id, expected_role),
    )
    if not row:
        return False
    await execute(
        db_path,
        """
        UPDATE users
        SET status = 'fired', fired_at = ?, fired_by_tg_user_id = ?
        WHERE tg_user_id = ? AND role = ?
        """,
        (now_utc_iso(), fired_by_tg_user_id, tg_user_id, expected_role),
    )
    return True


async def restore_user(
    db_path: str,
    tg_user_id: int,
    expected_role: str,
) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT tg_user_id
        FROM users
        WHERE tg_user_id = ? AND role = ? AND status = 'fired'
        """,
        (tg_user_id, expected_role),
    )
    if not row:
        return False
    await execute(
        db_path,
        """
        UPDATE users
        SET status = 'active', fired_at = NULL, fired_by_tg_user_id = NULL
        WHERE tg_user_id = ? AND role = ?
        """,
        (tg_user_id, expected_role),
    )
    return True


async def add_requisites(db_path: str, tg_user_id: int, content: str) -> None:
    encrypted = _encrypt_sensitive(content)
    await execute(
        db_path,
        """
        INSERT INTO requisites_history (tg_user_id, content, created_at)
        VALUES (?, ?, ?)
        """,
        (tg_user_id, encrypted, now_utc_iso()),
    )


async def get_requisites_history(db_path: str, tg_user_id: int) -> List[dict[str, Any]]:
    rows = await fetch_all(
        db_path,
        """
        SELECT id, content, created_at
        FROM requisites_history
        WHERE tg_user_id = ?
        ORDER BY created_at DESC
        """,
        (tg_user_id,),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["content"] = _decrypt_sensitive(str(item.get("content", "")))
        result.append(item)
    return result


async def has_requisites(db_path: str, tg_user_id: int) -> bool:
    row = await fetch_one(
        db_path,
        "SELECT 1 AS ok FROM requisites_history WHERE tg_user_id = ? LIMIT 1",
        (tg_user_id,),
    )
    return row is not None


async def get_latest_requisites(db_path: str, tg_user_id: int) -> Optional[dict[str, Any]]:
    row = await fetch_one(
        db_path,
        """
        SELECT id, content, created_at
        FROM requisites_history
        WHERE tg_user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (tg_user_id,),
    )
    if row is None:
        return None
    item = dict(row)
    item["content"] = _decrypt_sensitive(str(item.get("content", "")))
    return item


async def add_medcoin_ledger_entry(
    db_path: str,
    tg_user_id: int,
    company_group_id: int,
    org_id: int,
    entry_kind: str,
    stage_code: str,
    amount: float,
    available_delta: float,
    frozen_delta: float,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
    comment: str | None = None,
) -> int:
    created_at = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO medcoin_ledger (
                tg_user_id,
                company_group_id,
                org_id,
                entry_kind,
                stage_code,
                amount,
                available_delta,
                frozen_delta,
                related_entity_type,
                related_entity_id,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_user_id,
                company_group_id,
                org_id,
                entry_kind,
                stage_code,
                amount,
                available_delta,
                frozen_delta,
                related_entity_type,
                related_entity_id,
                comment,
                created_at,
            ),
        )
        await db.commit()
        return int(cur.lastrowid)


async def ensure_base_medcoin_earnings_for_claims(
    db_path: str,
    tg_user_id: int,
    company_group_id: int,
    org_id: int,
) -> int:
    rows = await fetch_all(
        db_path,
        """
        SELECT c.id AS claim_id, t.volume_goods
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        LEFT JOIN medcoin_ledger l
          ON l.related_entity_type = 'sales_claim'
         AND l.related_entity_id = c.id
         AND l.stage_code = 'base_claim'
        WHERE c.claimed_by_tg_user_id = ?
          AND l.id IS NULL
        ORDER BY c.id ASC
        """,
        (tg_user_id,),
    )
    if not rows:
        return 0
    created_at = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        for row in rows:
            volume = float(row["volume_goods"] or 0)
            await db.execute(
                """
                INSERT INTO medcoin_ledger (
                    tg_user_id,
                    company_group_id,
                    org_id,
                    entry_kind,
                    stage_code,
                    amount,
                    available_delta,
                    frozen_delta,
                    related_entity_type,
                    related_entity_id,
                    comment,
                    created_at
                )
                VALUES (?, ?, ?, 'earn', 'base_claim', ?, ?, 0, 'sales_claim', ?, 'Base earn by claimed volume', ?)
                """,
                (
                    tg_user_id,
                    company_group_id,
                    org_id,
                    volume,
                    volume,
                    int(row["claim_id"]),
                    created_at,
                ),
            )
        await db.commit()
    return len(rows)


async def get_medcoin_totals(db_path: str, tg_user_id: int) -> dict[str, float]:
    row = await fetch_one(
        db_path,
        """
        SELECT
            COALESCE(SUM(available_delta), 0) AS available,
            COALESCE(SUM(frozen_delta), 0) AS frozen,
            COALESCE(SUM(CASE WHEN entry_kind = 'earn' THEN amount ELSE 0 END), 0) AS earned_total,
            COALESCE(SUM(CASE WHEN entry_kind = 'withdraw' THEN ABS(amount) ELSE 0 END), 0) AS withdrawn_total
        FROM medcoin_ledger
        WHERE tg_user_id = ?
        """,
        (tg_user_id,),
    )
    return {
        "available": float(row["available"]) if row else 0.0,
        "frozen": float(row["frozen"]) if row else 0.0,
        "earned_total": float(row["earned_total"]) if row else 0.0,
        "withdrawn_total": float(row["withdrawn_total"]) if row else 0.0,
    }


async def get_dispute_frozen_amount(db_path: str, tg_user_id: int) -> float:
    row = await fetch_one(
        db_path,
        """
        SELECT COALESCE(SUM(t.volume_goods), 0) AS frozen
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND c.dispute_status = 'open'
        """,
        (tg_user_id,),
    )
    return float(row["frozen"]) if row else 0.0


async def create_withdrawal_request(
    db_path: str,
    tg_user_id: int,
    company_group_id: int,
    org_id: int,
    manager_tg_user_id: int,
    requisites_text: str,
    amount: float,
) -> int:
    if amount <= 0:
        raise ValueError("Amount must be positive")
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        totals_cur = await db.execute(
            """
            SELECT COALESCE(SUM(available_delta), 0) AS available
            FROM medcoin_ledger
            WHERE tg_user_id = ?
            """,
            (tg_user_id,),
        )
        totals_row = await totals_cur.fetchone()
        available = float(totals_row["available"]) if totals_row else 0.0
        frozen_cur = await db.execute(
            """
            SELECT COALESCE(SUM(t.volume_goods), 0) AS frozen
            FROM sales_claims c
            JOIN chz_turnover t ON t.id = c.turnover_id
            WHERE c.claimed_by_tg_user_id = ?
              AND c.dispute_status = 'open'
            """,
            (tg_user_id,),
        )
        frozen_row = await frozen_cur.fetchone()
        frozen_disputes = float(frozen_row["frozen"]) if frozen_row else 0.0
        available_for_withdraw = max(0.0, available - frozen_disputes)
        if amount > available_for_withdraw:
            await db.rollback()
            raise ValueError("Insufficient funds")
        encrypted_requisites = _encrypt_sensitive(requisites_text)
        cur = await db.execute(
            """
            INSERT INTO withdrawal_requests (
                tg_user_id,
                company_group_id,
                org_id,
                requisites_text,
                amount,
                status,
                manager_tg_user_id,
                requested_at
            )
            VALUES (?, ?, ?, ?, ?, 'requested', ?, ?)
            """,
            (
                tg_user_id,
                company_group_id,
                org_id,
                encrypted_requisites,
                amount,
                manager_tg_user_id,
                now_iso,
            ),
        )
        withdrawal_id = int(cur.lastrowid)
        await db.execute(
            """
            INSERT INTO medcoin_ledger (
                tg_user_id,
                company_group_id,
                org_id,
                entry_kind,
                stage_code,
                amount,
                available_delta,
                frozen_delta,
                related_entity_type,
                related_entity_id,
                comment,
                created_at
            )
            VALUES (?, ?, ?, 'withdraw', 'withdrawal_request', ?, ?, 0, 'withdrawal_request', ?, 'Withdrawal request created', ?)
            """,
            (
                tg_user_id,
                company_group_id,
                org_id,
                -amount,
                -amount,
                withdrawal_id,
                now_iso,
            ),
        )
        await db.commit()
    return withdrawal_id


async def list_finance_months(db_path: str, tg_user_id: int) -> list[str]:
    rows = await fetch_all(
        db_path,
        """
        SELECT month FROM (
            SELECT substr(created_at, 1, 7) AS month
            FROM medcoin_ledger
            WHERE tg_user_id = ?
            UNION
            SELECT substr(requested_at, 1, 7) AS month
            FROM withdrawal_requests
            WHERE tg_user_id = ?
        )
        WHERE month IS NOT NULL AND length(month) = 7
        ORDER BY month DESC
        """,
        (tg_user_id, tg_user_id),
    )
    return [str(r["month"]) for r in rows]


async def get_month_ledger_totals(db_path: str, tg_user_id: int, month: str) -> dict[str, float]:
    row = await fetch_one(
        db_path,
        """
        SELECT
            COALESCE(SUM(CASE WHEN entry_kind = 'earn' THEN amount ELSE 0 END), 0) AS earned,
            COALESCE(SUM(CASE WHEN entry_kind = 'withdraw' THEN ABS(amount) ELSE 0 END), 0) AS withdrawn
        FROM medcoin_ledger
        WHERE tg_user_id = ?
          AND substr(created_at, 1, 7) = ?
        """,
        (tg_user_id, month),
    )
    return {
        "earned": float(row["earned"]) if row else 0.0,
        "withdrawn": float(row["withdrawn"]) if row else 0.0,
    }


async def list_month_bonus_breakdown(
    db_path: str, tg_user_id: int, month: str
) -> list[dict[str, float | str]]:
    rows = await fetch_all(
        db_path,
        """
        SELECT stage_code, COALESCE(SUM(amount), 0) AS amount
        FROM medcoin_ledger
        WHERE tg_user_id = ?
          AND entry_kind = 'earn'
          AND substr(created_at, 1, 7) = ?
        GROUP BY stage_code
        HAVING ABS(COALESCE(SUM(amount), 0)) > 0.000001
        ORDER BY stage_code
        """,
        (tg_user_id, month),
    )
    return [{"stage_code": str(r["stage_code"]), "amount": float(r["amount"])} for r in rows]


async def get_month_claim_metrics(db_path: str, tg_user_id: int, month: str) -> dict[str, float | int]:
    row = await fetch_one(
        db_path,
        """
        SELECT
            COALESCE(SUM(t.volume_goods), 0) AS liters,
            COUNT(*) AS claims_count
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND substr(t.period, 1, 7) = ?
        """,
        (tg_user_id, month),
    )
    return {
        "liters": float(row["liters"]) if row else 0.0,
        "claims_count": int(row["claims_count"]) if row else 0,
    }


async def count_new_buyer_inns_for_user_month(
    db_path: str, tg_user_id: int, company_group_id: int, month: str
) -> int:
    month_start = f"{month}-01"
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(DISTINCT t.buyer_inn) AS cnt
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND c.company_group_id_at_claim = ?
          AND substr(t.period, 1, 7) = ?
          AND NOT EXISTS (
              SELECT 1
              FROM sales_claims c2
              JOIN chz_turnover t2 ON t2.id = c2.turnover_id
              WHERE c2.company_group_id_at_claim = c.company_group_id_at_claim
                AND t2.buyer_inn = t.buyer_inn
                AND substr(t2.period, 1, 10) < ?
          )
        """,
        (tg_user_id, company_group_id, month, month_start),
    )
    return int(row["cnt"]) if row else 0


async def get_company_rank_for_user_org_month(
    db_path: str, tg_user_id: int, org_id: int, month: str
) -> int | None:
    row = await fetch_one(
        db_path,
        """
        WITH org_totals AS (
            SELECT
                c.claimed_by_tg_user_id AS tg_user_id,
                COALESCE(SUM(t.volume_goods), 0) AS total_volume
            FROM sales_claims c
            JOIN chz_turnover t ON t.id = c.turnover_id
            WHERE c.org_id_at_claim = ?
              AND substr(t.period, 1, 7) = ?
            GROUP BY c.claimed_by_tg_user_id
        ),
        ranked AS (
            SELECT
                tg_user_id,
                ROW_NUMBER() OVER (ORDER BY total_volume DESC, tg_user_id ASC) AS company_rank
            FROM org_totals
        )
        SELECT company_rank
        FROM ranked
        WHERE tg_user_id = ?
        """,
        (org_id, month, tg_user_id),
    )
    return int(row["company_rank"]) if row else None


async def get_claim_with_turnover(db_path: str, claim_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT
            c.*,
            t.period,
            t.volume_goods,
            t.buyer_inn,
            t.buyer_name
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.id = ?
        """,
        (claim_id,),
    )


async def get_company_group_created_at(db_path: str, company_group_id: int) -> str | None:
    row = await fetch_one(
        db_path,
        "SELECT created_at FROM company_groups WHERE id = ?",
        (company_group_id,),
    )
    return str(row["created_at"]) if row else None


async def upsert_pool_state_for_group(
    db_path: str,
    company_group_id: int,
    started_at: str,
    ends_at: str,
) -> None:
    await execute(
        db_path,
        """
        INSERT INTO pool_state (company_group_id, started_at, ends_at)
        VALUES (?, ?, ?)
        ON CONFLICT(company_group_id)
        DO UPDATE SET started_at = excluded.started_at, ends_at = excluded.ends_at
        """,
        (company_group_id, started_at, ends_at),
    )


async def get_pool_state_for_group(db_path: str, company_group_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT company_group_id, started_at, ends_at
        FROM pool_state
        WHERE company_group_id = ?
        """,
        (company_group_id,),
    )


async def create_supertask(
    db_path: str,
    region: int,
    target_inn: str,
    reward: float,
    created_by_tg_user_id: int,
) -> int:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO supertasks (
                region,
                target_inn,
                reward,
                status,
                created_by_tg_user_id,
                assigned_claim_id,
                assigned_tg_user_id,
                completed_claim_id,
                completed_tg_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'new', ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (region, target_inn, reward, created_by_tg_user_id, now_iso, now_iso),
        )
        await db.commit()
        return int(cur.lastrowid)


async def list_supertasks_active_by_buyer_inn(db_path: str, buyer_inn: str) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT *
        FROM supertasks
        WHERE target_inn = ?
          AND status IN ('new', 'occupied', 'pending')
        ORDER BY created_at ASC
        """,
        (buyer_inn,),
    )


async def list_active_supertasks_for_user(
    db_path: str, tg_user_id: int, company_group_id: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT s.*
        FROM supertasks s
        LEFT JOIN supertask_candidates c
          ON c.supertask_id = s.id
         AND c.tg_user_id = ?
         AND c.status IN ('pending', 'pending_dispute', 'won')
        WHERE s.status IN ('new', 'occupied', 'pending')
          AND (s.completed_tg_user_id IS NULL OR s.completed_tg_user_id = ? OR c.id IS NOT NULL)
        ORDER BY s.created_at DESC
        LIMIT 50
        """,
        (tg_user_id, tg_user_id),
    )


async def upsert_supertask_candidate(
    db_path: str,
    supertask_id: int,
    claim_id: int,
    tg_user_id: int,
    status: str,
) -> None:
    now_iso = now_utc_iso()
    await execute(
        db_path,
        """
        INSERT INTO supertask_candidates (
            supertask_id,
            claim_id,
            tg_user_id,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(supertask_id, claim_id)
        DO UPDATE SET
            tg_user_id = excluded.tg_user_id,
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (supertask_id, claim_id, tg_user_id, status, now_iso, now_iso),
    )


async def set_supertask_assignment(
    db_path: str,
    supertask_id: int,
    status: str,
    claim_id: int | None,
    tg_user_id: int | None,
) -> None:
    await execute(
        db_path,
        """
        UPDATE supertasks
        SET status = ?,
            assigned_claim_id = ?,
            assigned_tg_user_id = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (status, claim_id, tg_user_id, now_utc_iso(), supertask_id),
    )


async def close_supertask_with_winner(
    db_path: str,
    supertask_id: int,
    claim_id: int,
    tg_user_id: int,
) -> None:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE supertasks
            SET status = 'completed',
                completed_claim_id = ?,
                completed_tg_user_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (claim_id, tg_user_id, now_iso, supertask_id),
        )
        await db.execute(
            """
            UPDATE supertask_candidates
            SET status = CASE WHEN claim_id = ? THEN 'won' ELSE 'lost' END,
                updated_at = ?
            WHERE supertask_id = ?
            """,
            (claim_id, now_iso, supertask_id),
        )
        await db.commit()


async def list_latest_supertasks(db_path: str, limit: int = 50) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT *
        FROM supertasks
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


async def has_group_sales_before_period(
    db_path: str, company_group_id: int, buyer_inn: str, period_iso: str
) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT 1 AS ok
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.company_group_id_at_claim = ?
          AND t.buyer_inn = ?
          AND substr(t.period, 1, 10) < ?
        LIMIT 1
        """,
        (company_group_id, buyer_inn, period_iso),
    )
    return row is not None


async def get_new_buyer_award_by_buyer(
    db_path: str, company_group_id: int, buyer_inn: str
) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT *
        FROM new_buyer_awards
        WHERE company_group_id = ? AND buyer_inn = ?
        """,
        (company_group_id, buyer_inn),
    )


async def upsert_new_buyer_award(
    db_path: str,
    company_group_id: int,
    buyer_inn: str,
    claim_id: int,
    tg_user_id: int,
    reward: float,
) -> None:
    now_iso = now_utc_iso()
    await execute(
        db_path,
        """
        INSERT INTO new_buyer_awards (
            company_group_id,
            buyer_inn,
            claim_id,
            tg_user_id,
            reward,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_group_id, buyer_inn)
        DO UPDATE SET
            claim_id = excluded.claim_id,
            tg_user_id = excluded.tg_user_id,
            reward = excluded.reward
        """,
        (company_group_id, buyer_inn, claim_id, tg_user_id, reward, now_iso),
    )


async def delete_new_buyer_award(
    db_path: str, company_group_id: int, buyer_inn: str
) -> None:
    await execute(
        db_path,
        """
        DELETE FROM new_buyer_awards
        WHERE company_group_id = ? AND buyer_inn = ?
        """,
        (company_group_id, buyer_inn),
    )


async def get_claim_stage_award(
    db_path: str, claim_id: int, stage_code: str
) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT *
        FROM claim_stage_awards
        WHERE claim_id = ? AND stage_code = ?
        """,
        (claim_id, stage_code),
    )


async def set_claim_stage_award(
    db_path: str,
    claim_id: int,
    stage_code: str,
    tg_user_id: int | None,
    amount: float,
) -> None:
    await execute(
        db_path,
        """
        INSERT INTO claim_stage_awards (claim_id, stage_code, tg_user_id, amount, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(claim_id, stage_code)
        DO UPDATE SET tg_user_id = excluded.tg_user_id, amount = excluded.amount, updated_at = excluded.updated_at
        """,
        (claim_id, stage_code, tg_user_id, amount, now_utc_iso()),
    )


async def list_sellers_and_rops_active(db_path: str) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id
        FROM users
        WHERE role IN ('seller', 'rop') AND status = 'active'
        """,
    )


async def count_active_levels_for_user(db_path: str, tg_user_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM avg_levels
        WHERE tg_user_id = ? AND is_active = 1
        """,
        (tg_user_id,),
    )
    return int(row["cnt"]) if row else 0


async def create_avg_level(
    db_path: str,
    tg_user_id: int,
    target_liters: float,
    reward: float,
    starts_at: str,
    ends_at: str,
    created_by_tg_user_id: int,
) -> int:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO avg_levels (
                tg_user_id,
                target_liters,
                reward,
                starts_at,
                ends_at,
                is_active,
                created_by_tg_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                tg_user_id,
                target_liters,
                reward,
                starts_at,
                ends_at,
                created_by_tg_user_id,
                now_iso,
                now_iso,
            ),
        )
        avg_level_id = int(cur.lastrowid)
        await db.execute(
            """
            INSERT INTO avg_levels_history (
                avg_level_id,
                tg_user_id,
                action,
                payload_json,
                created_by_tg_user_id,
                created_at
            )
            VALUES (?, ?, 'create', ?, ?, ?)
            """,
            (
                avg_level_id,
                tg_user_id,
                json.dumps(
                    {
                        "target_liters": target_liters,
                        "reward": reward,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                    ensure_ascii=False,
                ),
                created_by_tg_user_id,
                now_iso,
            ),
        )
        await db.commit()
        return avg_level_id


async def list_active_avg_levels_for_user(db_path: str, tg_user_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT *
        FROM avg_levels
        WHERE tg_user_id = ?
          AND is_active = 1
          AND starts_at <= ?
          AND ends_at >= ?
        ORDER BY starts_at ASC
        """,
        (tg_user_id, now_utc_iso(), now_utc_iso()),
    )


async def has_avg_level_award(
    db_path: str, avg_level_id: int, tg_user_id: int, period_key: str
) -> bool:
    row = await fetch_one(
        db_path,
        """
        SELECT 1 AS ok
        FROM avg_level_awards
        WHERE avg_level_id = ? AND tg_user_id = ? AND period_key = ?
        LIMIT 1
        """,
        (avg_level_id, tg_user_id, period_key),
    )
    return row is not None


async def create_avg_level_award(
    db_path: str,
    avg_level_id: int,
    tg_user_id: int,
    period_key: str,
    claim_id: int | None,
    reward: float,
) -> int:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO avg_level_awards (
                avg_level_id,
                tg_user_id,
                period_key,
                claim_id,
                reward,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (avg_level_id, tg_user_id, period_key, claim_id, reward, now_iso),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_sum_liters_between(
    db_path: str, tg_user_id: int, start_iso: str, end_iso: str
) -> float:
    row = await fetch_one(
        db_path,
        """
        SELECT COALESCE(SUM(t.volume_goods), 0) AS liters
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND substr(t.period, 1, 10) BETWEEN ? AND ?
        """,
        (tg_user_id, start_iso[:10], end_iso[:10]),
    )
    return float(row["liters"]) if row else 0.0


async def list_active_sellers_with_metrics_current_month(
    db_path: str, org_id: int, month: str, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        WITH seller_totals AS (
            SELECT
                u.tg_user_id AS tg_user_id,
                COALESCE(u.full_name, '') AS full_name,
                COALESCE(SUM(t.volume_goods), 0) AS liters,
                COUNT(c.id) AS claims_count
            FROM users u
            LEFT JOIN sales_claims c ON c.claimed_by_tg_user_id = u.tg_user_id
            LEFT JOIN chz_turnover t
                   ON t.id = c.turnover_id
                  AND substr(t.period, 1, 7) = ?
            WHERE u.org_id = ?
              AND u.role = 'seller'
              AND u.status = 'active'
            GROUP BY u.tg_user_id, u.full_name
        ),
        ranked AS (
            SELECT
                tg_user_id,
                full_name,
                liters,
                claims_count,
                ROW_NUMBER() OVER (ORDER BY liters DESC, tg_user_id ASC) AS company_rank
            FROM seller_totals
        )
        SELECT *
        FROM ranked
        ORDER BY company_rank ASC
        LIMIT ? OFFSET ?
        """,
        (month, org_id, limit, offset),
    )


async def count_active_sellers_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM users
        WHERE org_id = ? AND role = 'seller' AND status = 'active'
        """,
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def get_user_month_metrics(
    db_path: str, tg_user_id: int, month: str
) -> dict[str, float | int]:
    row = await fetch_one(
        db_path,
        """
        SELECT
            COALESCE(SUM(t.volume_goods), 0) AS liters,
            COUNT(c.id) AS claims_count
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
          AND substr(t.period, 1, 7) = ?
        """,
        (tg_user_id, month),
    )
    return {
        "liters": float(row["liters"]) if row else 0.0,
        "claims_count": int(row["claims_count"]) if row else 0,
    }


async def list_claimed_sales_for_user_all_time(db_path: str, tg_user_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT
            t.period,
            t.buyer_inn,
            t.buyer_name,
            t.volume_goods,
            t.nomenclature,
            c.claimed_at,
            c.dispute_status
        FROM sales_claims c
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.claimed_by_tg_user_id = ?
        ORDER BY substr(t.period, 1, 10) DESC, c.claimed_at DESC
        """,
        (tg_user_id,),
    )


async def count_unclaimed_turnover(
    db_path: str, seller_inn: str, launch_date_iso: str | None = None
) -> int:
    return await count_unclaimed_turnover_by_inns(db_path, [seller_inn], launch_date_iso)


async def count_unclaimed_turnover_by_inns(
    db_path: str, seller_inns: list[str], launch_date_iso: str | None = None
) -> int:
    if not seller_inns:
        return 0
    placeholders = ",".join("?" for _ in seller_inns)
    where_launch = " AND substr(t.period, 1, 10) >= ? " if launch_date_iso else ""
    params: tuple = tuple(seller_inns) + ((launch_date_iso,) if launch_date_iso else ())
    row = await fetch_one(
        db_path,
        f"""
        SELECT COUNT(*) AS cnt
        FROM chz_turnover t
        LEFT JOIN sales_claims c ON c.turnover_id = t.id
        WHERE t.seller_inn IN ({placeholders}) AND c.turnover_id IS NULL {where_launch}
        """,
        params,
    )
    return int(row["cnt"]) if row else 0


async def list_unclaimed_turnover(
    db_path: str, seller_inn: str, limit: int, offset: int, launch_date_iso: str | None = None
) -> List[aiosqlite.Row]:
    return await list_unclaimed_turnover_by_inns(
        db_path, [seller_inn], limit, offset, launch_date_iso
    )


async def list_unclaimed_turnover_by_inns(
    db_path: str,
    seller_inns: list[str],
    limit: int,
    offset: int,
    launch_date_iso: str | None = None,
) -> List[aiosqlite.Row]:
    if not seller_inns:
        return []
    placeholders = ",".join("?" for _ in seller_inns)
    where_launch = " AND substr(t.period, 1, 10) >= ? " if launch_date_iso else ""
    params: tuple = tuple(seller_inns)
    if launch_date_iso:
        params = params + (launch_date_iso,)
    params = params + (limit, offset)
    return await fetch_all(
        db_path,
        f"""
        SELECT t.id, t.period, t.nomenclature, t.volume_goods, t.buyer_inn, t.buyer_name, t.seller_inn
        FROM chz_turnover t
        LEFT JOIN sales_claims c ON c.turnover_id = t.id
        WHERE t.seller_inn IN ({placeholders}) AND c.turnover_id IS NULL {where_launch}
        ORDER BY t.period DESC, t.id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )


async def get_turnover_by_id(db_path: str, turnover_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(db_path, "SELECT * FROM chz_turnover WHERE id = ?", (turnover_id,))


async def is_turnover_claimed(db_path: str, turnover_id: int) -> bool:
    row = await fetch_one(
        db_path,
        "SELECT 1 AS exists_flag FROM sales_claims WHERE turnover_id = ?",
        (turnover_id,),
    )
    return row is not None


async def claim_turnover(db_path: str, turnover_id: int, tg_user_id: int) -> None:
    user = await get_user_by_tg_id(db_path, tg_user_id)
    if not user:
        raise ValueError("User is not registered")
    await execute(
        db_path,
        """
        INSERT INTO sales_claims (
            turnover_id,
            claimed_by_tg_user_id,
            claimed_at,
            company_group_id_at_claim,
            org_id_at_claim
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            turnover_id,
            tg_user_id,
            now_utc_iso(),
            int(user["company_group_id"]),
            int(user["org_id"]),
        ),
    )


async def list_claimed_sales_for_dispute(
    db_path: str,
    company_group_id: int,
    viewer_tg_user_id: int,
    viewer_role: str,
    limit: int,
    offset: int,
) -> List[aiosqlite.Row]:
    params: list[Any] = [company_group_id]
    where_own = ""
    if viewer_role == "seller":
        where_own = " AND c.claimed_by_tg_user_id <> ? "
        params.append(viewer_tg_user_id)
    params.extend([limit, offset])
    return await fetch_all(
        db_path,
        f"""
        SELECT
            c.id AS claim_id,
            c.turnover_id AS turnover_id,
            c.claimed_by_tg_user_id AS claimed_by_tg_user_id,
            c.claimed_at AS claimed_at,
            COALESCE(u.full_name, '') AS claimed_by_full_name,
            t.period AS period,
            t.buyer_inn AS buyer_inn,
            t.buyer_name AS buyer_name,
            t.volume_goods AS volume_goods
        FROM sales_claims c
        LEFT JOIN users u ON u.tg_user_id = c.claimed_by_tg_user_id
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.company_group_id_at_claim = ?
          AND c.dispute_status <> 'open'
          {where_own}
        ORDER BY c.claimed_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )


async def count_claimed_sales_for_dispute(
    db_path: str,
    company_group_id: int,
    viewer_tg_user_id: int,
    viewer_role: str,
) -> int:
    params: list[Any] = [company_group_id]
    where_own = ""
    if viewer_role == "seller":
        where_own = " AND c.claimed_by_tg_user_id <> ? "
        params.append(viewer_tg_user_id)
    row = await fetch_one(
        db_path,
        f"""
        SELECT COUNT(*) AS cnt
        FROM sales_claims c
        WHERE c.company_group_id_at_claim = ?
          AND c.dispute_status <> 'open'
          {where_own}
        """,
        tuple(params),
    )
    return int(row["cnt"]) if row else 0


async def get_claim_by_id(db_path: str, claim_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT c.*, t.period, t.buyer_inn, t.buyer_name, t.volume_goods
        FROM sales_claims c
        LEFT JOIN users u ON u.tg_user_id = c.claimed_by_tg_user_id
        JOIN chz_turnover t ON t.id = c.turnover_id
        WHERE c.id = ?
        """,
        (claim_id,),
    )


async def get_open_dispute_for_claim(db_path: str, claim_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT *
        FROM sale_disputes
        WHERE claim_id = ? AND status = 'open'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (claim_id,),
    )


async def create_sale_dispute(
    db_path: str,
    claim_id: int,
    initiator_tg_user_id: int,
    moderator_tg_user_id: int,
) -> int:
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        claim_cur = await db.execute(
            """
            SELECT id, turnover_id, company_group_id_at_claim, org_id_at_claim,
                   claimed_by_tg_user_id, dispute_status
            FROM sales_claims
            WHERE id = ?
            """,
            (claim_id,),
        )
        claim = await claim_cur.fetchone()
        if not claim:
            await db.rollback()
            raise ValueError("Claim not found")
        if str(claim["dispute_status"]) == "open":
            await db.rollback()
            raise ValueError("Dispute already open")
        cur = await db.execute(
            """
            INSERT INTO sale_disputes (
                claim_id,
                turnover_id,
                company_group_id,
                org_id,
                initiator_tg_user_id,
                claimed_by_tg_user_id,
                moderator_tg_user_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                int(claim["id"]),
                int(claim["turnover_id"]),
                int(claim["company_group_id_at_claim"]),
                int(claim["org_id_at_claim"]),
                initiator_tg_user_id,
                int(claim["claimed_by_tg_user_id"]),
                moderator_tg_user_id,
                now_iso,
                now_iso,
            ),
        )
        dispute_id = cur.lastrowid
        updated = await db.execute(
            """
            UPDATE sales_claims
            SET dispute_status = 'open', dispute_id = ?
            WHERE id = ? AND dispute_status <> 'open'
            """,
            (dispute_id, claim_id),
        )
        if updated.rowcount == 0:
            await db.rollback()
            raise ValueError("Dispute already open")
        await db.commit()
        return int(dispute_id)


async def get_dispute_by_id(db_path: str, dispute_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(
        db_path,
        """
        SELECT d.*, t.period, t.buyer_inn, t.buyer_name, t.volume_goods, c.claimed_at,
               COALESCE(u1.full_name, '') AS initiator_full_name,
               COALESCE(u2.full_name, '') AS claimed_by_full_name,
               COALESCE(u3.full_name, '') AS moderator_full_name
        FROM sale_disputes d
        JOIN chz_turnover t ON t.id = d.turnover_id
        JOIN sales_claims c ON c.id = d.claim_id
        LEFT JOIN users u1 ON u1.tg_user_id = d.initiator_tg_user_id
        LEFT JOIN users u2 ON u2.tg_user_id = d.claimed_by_tg_user_id
        LEFT JOIN users u3 ON u3.tg_user_id = d.moderator_tg_user_id
        WHERE d.id = ?
        """,
        (dispute_id,),
    )


async def list_open_disputes_by_initiator(db_path: str, tg_user_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT d.*, t.period, t.buyer_inn, t.buyer_name, t.volume_goods,
               COALESCE(u1.full_name, '') AS claimed_by_full_name
        FROM sale_disputes d
        JOIN chz_turnover t ON t.id = d.turnover_id
        LEFT JOIN users u1 ON u1.tg_user_id = d.claimed_by_tg_user_id
        WHERE d.initiator_tg_user_id = ? AND d.status = 'open'
        ORDER BY d.created_at DESC
        """,
        (tg_user_id,),
    )


async def list_open_disputes_against_user(db_path: str, tg_user_id: int) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT d.*, t.period, t.buyer_inn, t.buyer_name, t.volume_goods,
               COALESCE(u1.full_name, '') AS initiator_full_name
        FROM sale_disputes d
        JOIN chz_turnover t ON t.id = d.turnover_id
        LEFT JOIN users u1 ON u1.tg_user_id = d.initiator_tg_user_id
        WHERE d.claimed_by_tg_user_id = ?
          AND d.initiator_tg_user_id <> ?
          AND d.status = 'open'
        ORDER BY d.created_at DESC
        """,
        (tg_user_id, tg_user_id),
    )


async def list_open_disputes_for_moderator(
    db_path: str, moderator_tg_user_id: int, company_group_id: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT d.*, t.period, t.buyer_inn, t.buyer_name, t.volume_goods,
               COALESCE(u1.full_name, '') AS initiator_full_name,
               COALESCE(u2.full_name, '') AS claimed_by_full_name
        FROM sale_disputes d
        JOIN chz_turnover t ON t.id = d.turnover_id
        LEFT JOIN users u1 ON u1.tg_user_id = d.initiator_tg_user_id
        LEFT JOIN users u2 ON u2.tg_user_id = d.claimed_by_tg_user_id
        WHERE d.company_group_id = ?
          AND d.status = 'open'
          AND d.moderator_tg_user_id = ?
        ORDER BY d.created_at DESC
        """,
        (company_group_id, moderator_tg_user_id),
    )


async def cancel_dispute(db_path: str, dispute_id: int, initiator_tg_user_id: int) -> bool:
    dispute = await get_dispute_by_id(db_path, dispute_id)
    if not dispute:
        return False
    if int(dispute["initiator_tg_user_id"]) != initiator_tg_user_id:
        return False
    if str(dispute["status"]) != "open":
        return False
    now_iso = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE sale_disputes
            SET status = 'canceled', canceled_at = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (now_iso, now_iso, dispute_id),
        )
        await db.execute(
            """
            UPDATE sales_claims
            SET dispute_status = 'none', dispute_id = NULL
            WHERE id = ?
            """,
            (int(dispute["claim_id"]),),
        )
        await db.commit()
    return True


async def resolve_dispute(
    db_path: str,
    dispute_id: int,
    moderator_tg_user_id: int,
    approve: bool,
) -> bool:
    dispute = await get_dispute_by_id(db_path, dispute_id)
    if not dispute:
        return False
    if int(dispute["moderator_tg_user_id"]) != moderator_tg_user_id:
        return False
    if str(dispute["status"]) != "open":
        return False
    now_iso = now_utc_iso()
    status = "approved" if approve else "rejected"
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            UPDATE sale_disputes
            SET status = ?, resolved_at = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (status, now_iso, now_iso, dispute_id),
        )
        if cur.rowcount == 0:
            await db.rollback()
            return False
        if approve:
            await db.execute(
                """
                UPDATE sales_claims
                SET claimed_by_tg_user_id = ?,
                    claimed_at = ?,
                    dispute_status = 'none',
                    dispute_id = NULL
                WHERE id = ?
                """,
                (
                    int(dispute["initiator_tg_user_id"]),
                    now_iso,
                    int(dispute["claim_id"]),
                ),
            )
        else:
            await db.execute(
                """
                UPDATE sales_claims
                SET dispute_status = 'none', dispute_id = NULL
                WHERE id = ?
                """,
                (int(dispute["claim_id"]),),
            )
        await db.commit()
    return True


async def upsert_chz_turnover(db_path: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "upserted_count": 0,
            "inserted_count": 0,
            "affected_seller_inns": [],
            "affected_company_group_ids": [],
        }
    query_upsert = """
        INSERT INTO chz_turnover (
            period,
            type_operation,
            nomenclature,
            volume_goods,
            volume_partial,
            seller_inn,
            seller_name,
            buyer_inn,
            buyer_name,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
            period,
            type_operation,
            nomenclature,
            seller_inn,
            seller_name,
            buyer_inn,
            buyer_name
        )
        DO UPDATE SET
            volume_goods = excluded.volume_goods,
            volume_partial = excluded.volume_partial,
            updated_at = excluded.updated_at
    """
    query_insert_new = """
        INSERT INTO chz_turnover (
            period,
            type_operation,
            nomenclature,
            volume_goods,
            volume_partial,
            seller_inn,
            seller_name,
            buyer_inn,
            buyer_name,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
            period,
            type_operation,
            nomenclature,
            seller_inn,
            seller_name,
            buyer_inn,
            buyer_name
        )
        DO NOTHING
        RETURNING seller_inn
    """
    now_iso = now_utc_iso()
    params = [
        (
            row["period"],
            row["type_operation"],
            row["nomenclature"],
            row["volume_goods"],
            row["volume_partial"],
            row["seller_inn"],
            row["seller_name"],
            row["buyer_inn"],
            row["buyer_name"],
            now_iso,
        )
        for row in rows
    ]
    inserted_seller_inns: set[str] = set()
    inserted_count = 0
    async with aiosqlite.connect(db_path) as db:
        for row_params in params:
            cur = await db.execute(query_insert_new, row_params)
            inserted = await cur.fetchone()
            if inserted and inserted[0]:
                inserted_count += 1
                inserted_seller_inns.add(str(inserted[0]))
        await db.executemany(query_upsert, params)
        await db.commit()

    company_group_ids: list[int] = []
    if inserted_seller_inns:
        placeholders = ",".join("?" for _ in inserted_seller_inns)
        rows_groups = await fetch_all(
            db_path,
            f"""
            SELECT DISTINCT company_group_id
            FROM org_inns
            WHERE inn IN ({placeholders}) AND is_active = 1
            """,
            tuple(sorted(inserted_seller_inns)),
        )
        company_group_ids = [int(r["company_group_id"]) for r in rows_groups]

    return {
        "upserted_count": len(rows),
        "inserted_count": inserted_count,
        "affected_seller_inns": sorted(inserted_seller_inns),
        "affected_company_group_ids": sorted(company_group_ids),
    }
