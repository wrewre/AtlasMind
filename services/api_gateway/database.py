"""
PostgreSQL Database Layer (Neon)
================================
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

import asyncpg
import structlog

log = structlog.get_logger("database")

DATABASE_URL  = os.getenv("DATABASE_URL")
HISTORY_LIMIT = 10

# Global connection pool
_pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    """Create connection pool and tables if they don't exist. Called on app startup."""
    global _pool
    if not DATABASE_URL:
        log.warning("DATABASE_URL not set. Database will not be initialized.")
        return

    try:
        # Neon postgres requires SSL, asyncpg supports it natively when DSN starts with postgres(ql)://
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=10)
        
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            VARCHAR PRIMARY KEY,
                    username      VARCHAR UNIQUE NOT NULL,
                    email         VARCHAR,
                    password_hash VARCHAR NOT NULL,
                    created_at    TIMESTAMPTZ NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_documents (
                    id              VARCHAR PRIMARY KEY,
                    user_id         VARCHAR NOT NULL,
                    document_id     VARCHAR NOT NULL UNIQUE,
                    filename        VARCHAR NOT NULL,
                    processed_at    TIMESTAMPTZ,
                    node_count      INTEGER DEFAULT 0,
                    edge_count      INTEGER DEFAULT 0,
                    summary_snippet VARCHAR,
                    created_at      TIMESTAMPTZ NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_docs ON user_documents(user_id, created_at DESC)"
            )
        log.info("postgres_db_initialized", pool_size=10)
    except Exception as e:
        log.error("db_initialization_failed", error=str(e))
        raise

async def close_db() -> None:
    """Close the database pool. Called on app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        log.info("postgres_db_closed")


async def create_user(
    username: str, password_hash: str, email: Optional[str] = None
) -> Optional[Dict]:
    """Create a new user. Returns user dict or None if username taken."""
    if not _pool:
        return None
        
    user_id = str(uuid.uuid4())
    now     = datetime.utcnow()
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, email, password_hash, created_at) VALUES ($1, $2, $3, $4, $5)",
                user_id, username, email, password_hash, now
            )
        return {"id": user_id, "username": username, "email": email, "created_at": now.isoformat()}
    except asyncpg.UniqueViolationError:
        return None


async def get_user_by_username(username: str) -> Optional[Dict]:
    """Fetch user by username for login."""
    if not _pool:
        return None
        
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, email, password_hash, created_at FROM users WHERE username = $1",
            username
        )
        if row:
            res = dict(row)
            res['created_at'] = res['created_at'].isoformat() if res['created_at'] else None
            return res
        return None


async def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Fetch user by ID."""
    if not _pool:
        return None
        
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, email, created_at FROM users WHERE id = $1",
            user_id
        )
        if row:
            res = dict(row)
            res['created_at'] = res['created_at'].isoformat() if res['created_at'] else None
            return res
        return None


async def add_document_to_history(
    user_id: str,
    document_id: str,
    filename: str,
) -> None:
    """
    Add a document to user history. Auto-deletes oldest if > HISTORY_LIMIT.
    Called immediately on upload so the document appears in history right away.
    """
    if not _pool:
        return
        
    doc_id = str(uuid.uuid4())
    now    = datetime.utcnow()
    
    async with _pool.acquire() as conn:
        async with conn.transaction():
            # Upsert — if document_id already exists (re-upload), update it
            await conn.execute(
                """
                INSERT INTO user_documents (id, user_id, document_id, filename, created_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT(document_id) DO UPDATE SET filename = EXCLUDED.filename
                """,
                doc_id, user_id, document_id, filename, now
            )

            # Enforce 10-document limit — delete oldest beyond limit
            old_rows = await conn.fetch(
                """
                SELECT id FROM user_documents
                WHERE user_id = $1
                ORDER BY created_at DESC
                OFFSET $2
                """,
                user_id, HISTORY_LIMIT
            )

            if old_rows:
                old_ids = [r['id'] for r in old_rows]
                await conn.execute(
                    "DELETE FROM user_documents WHERE id = ANY($1)", 
                    old_ids
                )
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
    if not _pool:
        return
        
    # parse ISO string to datetime for postgres if needed
    processed_at_dt = None
    if processed_at:
        try:
            processed_at_dt = datetime.fromisoformat(processed_at.replace('Z', '+00:00'))
        except ValueError:
            processed_at_dt = datetime.utcnow()
            
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_documents
            SET node_count = $1, edge_count = $2, summary_snippet = $3, processed_at = $4
            WHERE document_id = $5 AND user_id = $6
            """,
            node_count, edge_count, summary_snippet[:300] if summary_snippet else None, processed_at_dt, document_id, user_id
        )


async def get_user_history(user_id: str) -> List[Dict]:
    """Return user's document history, newest first, up to HISTORY_LIMIT."""
    if not _pool:
        return []
        
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT document_id, filename, processed_at, node_count, edge_count,
                   summary_snippet, created_at
            FROM user_documents
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, HISTORY_LIMIT
        )
        
        results = []
        for r in rows:
            d = dict(r)
            d['created_at'] = d['created_at'].isoformat() if d['created_at'] else None
            d['processed_at'] = d['processed_at'].isoformat() if d['processed_at'] else None
            results.append(d)
            
        return results


async def delete_user_document(document_id: str, user_id: str) -> bool:
    """Delete a document from user history. Returns True if deleted."""
    if not _pool:
        return False
        
    async with _pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM user_documents WHERE document_id = $1 AND user_id = $2",
            document_id, user_id
        )
        return status != "DELETE 0"
