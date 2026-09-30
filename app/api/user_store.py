"""
Persistent user storage backed by the configurator PostgreSQL database.
Uses the same CONFIGURATOR_DB_* env vars but opens a read-write connection.
Table blos.app_users is pre-created in the DB.
"""
from __future__ import annotations

import contextlib
import logging
import threading

from app.api.db_pool import get_conn, put_conn

logger = logging.getLogger(__name__)
_init_lock = threading.Lock()
_table_ready = False


@contextlib.contextmanager
def _cursor():
    import psycopg2
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
        put_conn(conn)
    except psycopg2.OperationalError:
        # Stale connection — discard and let caller retry via _ensure_table or direct call
        put_conn(conn, discard=True)
        raise
    except Exception:
        conn.rollback()
        put_conn(conn, discard=True)
        raise


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _init_lock:
        if _table_ready:
            return
        # Table is pre-created in blos schema — just verify access
        with _cursor() as cur:
            cur.execute("SELECT 1 FROM blos.app_users LIMIT 1")
        _table_ready = True
        logger.info("blos.app_users table ready")


def list_all_users() -> list[dict]:
    _ensure_table()
    with _cursor() as cur:
        cur.execute("SELECT user_id, username, created_at FROM blos.app_users ORDER BY created_at")
        rows = cur.fetchall()
    return [
        {"user_id": r[0], "username": r[1], "created_at": r[2].isoformat() if r[2] else None}
        for r in rows
    ]


def get_user(username: str) -> dict | None:
    _ensure_table()
    with _cursor() as cur:
        cur.execute(
            "SELECT user_id, username, hashed_password FROM blos.app_users WHERE username = %s",
            (username.lower(),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"user_id": row[0], "username": row[1], "hashed_password": row[2]}


def delete_user(user_id: str) -> bool:
    _ensure_table()
    with _cursor() as cur:
        cur.execute("DELETE FROM blos.app_users WHERE user_id = %s", (user_id,))
        return cur.rowcount > 0


def create_user(username: str, user_id: str, hashed_password: str) -> None:
    _ensure_table()
    try:
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO blos.app_users (username, user_id, hashed_password) VALUES (%s, %s, %s)",
                (username.lower(), user_id, hashed_password),
            )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise ValueError("Username already taken")
        raise
