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
                last_seen_at TEXT
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
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orgs_created_by ON organizations(created_by_manager_id)"
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
    db_path: str, tg_user_id: int, org_id: int, registered_at: str, last_seen_at: str
) -> None:
    await execute(
        db_path,
        """
        INSERT INTO users (tg_user_id, org_id, role, registered_at, last_seen_at)
        VALUES (?, ?, 'seller', ?, ?)
        """,
        (tg_user_id, org_id, registered_at, last_seen_at),
    )


async def update_last_seen(db_path: str, tg_user_id: int) -> None:
    await execute(
        db_path,
        "UPDATE users SET last_seen_at = ? WHERE tg_user_id = ?",
        (now_utc_iso(), tg_user_id),
    )
