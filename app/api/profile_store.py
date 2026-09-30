"""
Persistent template-profile storage backed by PostgreSQL.

Profiles are written here during resolve_run so they survive Railway
container restarts. Uses the same CONFIGURATOR_DB_* env vars as user_store.
Table blos.template_profiles is auto-created on first use.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading

from app.api.db_pool import get_conn, put_conn

logger = logging.getLogger(__name__)
_init_lock = threading.Lock()
_table_ready = False


@contextlib.contextmanager
def _cursor():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
        put_conn(conn)
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
        with _cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS blos.template_profiles (
                    user_id     TEXT        NOT NULL,
                    template_id TEXT        NOT NULL,
                    profile     JSONB       NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, template_id)
                )
            """)
        _table_ready = True
        logger.info("blos.template_profiles table ready")


def save_profile(user_id: str, template_id: str, profile: dict) -> None:
    """Upsert a template profile into PostgreSQL."""
    try:
        _ensure_table()
        with _cursor() as cur:
            cur.execute("""
                INSERT INTO blos.template_profiles (user_id, template_id, profile, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (user_id, template_id)
                DO UPDATE SET profile = EXCLUDED.profile, updated_at = NOW()
            """, (user_id, template_id, json.dumps(profile)))
    except Exception as exc:
        logger.warning("profile_store.save_profile failed: %s", type(exc).__name__)


def load_profile(user_id: str, template_id: str) -> dict | None:
    """Load a template profile from PostgreSQL. Returns None if not found."""
    try:
        _ensure_table()
        with _cursor() as cur:
            cur.execute(
                "SELECT profile FROM blos.template_profiles WHERE user_id = %s AND template_id = %s",
                (user_id, template_id),
            )
            row = cur.fetchone()
        if row:
            val = row[0]
            return val if isinstance(val, dict) else json.loads(val)
    except Exception as exc:
        logger.warning("profile_store.load_profile failed: %s", type(exc).__name__)
    return None
