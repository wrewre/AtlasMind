"""
SQLite Database Layer
======================
Manages user accounts and per-user document history.

Schema:
  users(id, username, email, password_hash, created_at)
  user_documents(id, user_id, document_id, filename, processed_at,
                 node_count, edge_count, summary_snippet, created_at)

History limit: 10 graphs per user — oldest auto-deleted when exceeded.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import aiosqlite
import structlog

log = structlog.get_logger("database")

SQLITE_PATH   = os.getenv("SQLITE_PATH", "/app/data/mindmap.db")
HISTORY_LIMIT = 10


async def init_db() -> None:
    """Create tables if they don't exist. Called on app startup."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           TEXT PRIMARY KEY,
                username     TEXT UNIQUE NOT NULL,
                email        TEXT,
                password_hash TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_documents (
                id              TEXT PRIMARY KEY,
                user_id         TEXT NOT NULL,
                document_id     TEXT NOT NULL UNIQUE,
                filename        TEXT NOT NULL,
                processed_at    TEXT,
                node_count      INTEGER DEFAULT 0,
                edge_count      INTEGER DEFAULT 0,
                summary_snippet TEXT,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_docs ON user_documents(user_id, created_at DESC)"
        )
        await db.commit()
    log.info("db_initialized", path=SQLITE_PATH)


async def create_user(
    username: str, password_hash: str, email: Optional[str] = None
) -> Optional[Dict]:
    """Create a new user. Returns user dict or None if username taken."""
    user_id = str(uuid.uuid4())
    now     = datetime.utcnow().isoformat()
    try:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute(
                "INSERT INTO users (id, username, email, password_hash, created_at) VALUES (?,?,?,?,?)",
                (user_id, username, email, password_hash, now),
            )
            await db.commit()
        return {"id": user_id, "username": username, "email": email, "created_at": now}
    except aiosqlite.IntegrityError:
        return None


async def get_user_by_username(username: str) -> Optional[Dict]:
    """Fetch user by username for login."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, username, email, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Fetch user by ID."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, username, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_document_to_history(
    user_id: str,
    document_id: str,
    filename: str,
) -> None:
    """
    Add a document to user history. Auto-deletes oldest if > HISTORY_LIMIT.
    Called immediately on upload so the document appears in history right away.
    """
    doc_id = str(uuid.uuid4())
    now    = datetime.utcnow().isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        # Upsert — if document_id already exists (re-upload), update it
        await db.execute(
            """
            INSERT INTO user_documents (id, user_id, document_id, filename, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET filename=excluded.filename
            """,
            (doc_id, user_id, document_id, filename, now),
        )
        await db.commit()

        # Enforce 10-document limit — delete oldest beyond limit
        async with db.execute(
            """
            SELECT id FROM user_documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
            """,
            (user_id, HISTORY_LIMIT),
        ) as cursor:
            old_rows = await cursor.fetchall()

        if old_rows:
            old_ids = [r[0] for r in old_rows]
            placeholders = ",".join("?" * len(old_ids))
            await db.execute(
                f"DELETE FROM user_documents WHERE id IN ({placeholders})", old_ids
            )
            await db.commit()
            log.info("history_limit_enforced", user_id=user_id, removed=len(old_ids))


async def update_document_stats(
    document_id: str,
    user_id: str,
    node_count: int,
    edge_count: int,
    summary_snippet: str,
    processed_at: str,
) -> None:
    """Update graph stats after processing completes."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            """
            UPDATE user_documents
            SET node_count=?, edge_count=?, summary_snippet=?, processed_at=?
            WHERE document_id=? AND user_id=?
            """,
            (node_count, edge_count, summary_snippet[:300], processed_at, document_id, user_id),
        )
        await db.commit()


async def get_user_history(user_id: str) -> List[Dict]:
    """Return user's document history, newest first, up to HISTORY_LIMIT."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT document_id, filename, processed_at, node_count, edge_count,
                   summary_snippet, created_at
            FROM user_documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, HISTORY_LIMIT),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def delete_user_document(document_id: str, user_id: str) -> bool:
    """Delete a document from user history. Returns True if deleted."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM user_documents WHERE document_id=? AND user_id=?",
            (document_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0
