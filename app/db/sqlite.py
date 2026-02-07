from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import aiosqlite

from app.utils.time import now_utc_iso


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inn TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_by_manager_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                password_rotated_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_user_id INTEGER PRIMARY KEY,
                org_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                last_seen_at TEXT,
                full_name TEXT
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
                claimed_at TEXT NOT NULL
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
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orgs_created_by ON organizations(created_by_manager_id)"
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
            CREATE INDEX IF NOT EXISTS idx_ratings_monthly_month
            ON ratings_monthly(month)
            """
        )
        await db.commit()

        # Backward-compatible migration for full_name in existing DBs
        async with db.execute("PRAGMA table_info(users)") as cursor:
            columns = [row[1] async for row in cursor]
        if "full_name" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
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
    return await fetch_one(db_path, "SELECT * FROM organizations WHERE inn = ?", (inn,))


async def get_org_by_id(db_path: str, org_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(db_path, "SELECT * FROM organizations WHERE id = ?", (org_id,))


async def create_org(
    db_path: str,
    inn: str,
    name: str,
    password_hash: str,
    created_by_manager_id: int,
) -> int:
    created_at = now_utc_iso()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO organizations (inn, name, password_hash, created_by_manager_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (inn, name, password_hash, created_by_manager_id, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def update_org_password(db_path: str, org_id: int, password_hash: str) -> None:
    await execute(
        db_path,
        """
        UPDATE organizations
        SET password_hash = ?, password_rotated_at = ?
        WHERE id = ?
        """,
        (password_hash, now_utc_iso(), org_id),
    )


async def list_orgs_by_manager(
    db_path: str, manager_id: int, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT * FROM organizations
        WHERE created_by_manager_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (manager_id, limit, offset),
    )


async def count_orgs_by_manager(db_path: str, manager_id: int) -> int:
    row = await fetch_one(
        db_path,
        "SELECT COUNT(*) AS cnt FROM organizations WHERE created_by_manager_id = ?",
        (manager_id,),
    )
    return int(row["cnt"]) if row else 0


async def count_sellers_by_org(db_path: str, org_id: int) -> int:
    row = await fetch_one(
        db_path,
        "SELECT COUNT(*) AS cnt FROM users WHERE org_id = ?",
        (org_id,),
    )
    return int(row["cnt"]) if row else 0


async def list_sellers_by_org(
    db_path: str, org_id: int, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT tg_user_id, registered_at
        FROM users
        WHERE org_id = ?
        ORDER BY registered_at DESC
        LIMIT ? OFFSET ?
        """,
        (org_id, limit, offset),
    )


async def get_user_by_tg_id(db_path: str, tg_user_id: int) -> Optional[aiosqlite.Row]:
    return await fetch_one(db_path, "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,))


async def create_user(
    db_path: str,
    tg_user_id: int,
    org_id: int,
    registered_at: str,
    last_seen_at: str,
    full_name: str,
) -> None:
    await execute(
        db_path,
        """
        INSERT INTO users (tg_user_id, org_id, role, registered_at, last_seen_at, full_name)
        VALUES (?, ?, 'seller', ?, ?, ?)
        """,
        (tg_user_id, org_id, registered_at, last_seen_at, full_name),
    )


async def update_last_seen(db_path: str, tg_user_id: int) -> None:
    await execute(
        db_path,
        "UPDATE users SET last_seen_at = ? WHERE tg_user_id = ?",
        (now_utc_iso(), tg_user_id),
    )


async def count_unclaimed_turnover(db_path: str, seller_inn: str) -> int:
    row = await fetch_one(
        db_path,
        """
        SELECT COUNT(*) AS cnt
        FROM chz_turnover t
        LEFT JOIN sales_claims c ON c.turnover_id = t.id
        WHERE t.seller_inn = ? AND c.turnover_id IS NULL
        """,
        (seller_inn,),
    )
    return int(row["cnt"]) if row else 0


async def list_unclaimed_turnover(
    db_path: str, seller_inn: str, limit: int, offset: int
) -> List[aiosqlite.Row]:
    return await fetch_all(
        db_path,
        """
        SELECT t.id, t.period, t.nomenclature, t.volume_goods, t.buyer_inn, t.buyer_name
        FROM chz_turnover t
        LEFT JOIN sales_claims c ON c.turnover_id = t.id
        WHERE t.seller_inn = ? AND c.turnover_id IS NULL
        ORDER BY t.period DESC, t.id DESC
        LIMIT ? OFFSET ?
        """,
        (seller_inn, limit, offset),
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
    await execute(
        db_path,
        """
        INSERT INTO sales_claims (turnover_id, claimed_by_tg_user_id, claimed_at)
        VALUES (?, ?, ?)
        """,
        (turnover_id, tg_user_id, now_utc_iso()),
    )


async def upsert_chz_turnover(db_path: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    query = """
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
    async with aiosqlite.connect(db_path) as db:
        await db.executemany(query, params)
        await db.commit()
    return len(rows)
