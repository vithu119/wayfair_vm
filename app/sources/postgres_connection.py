from __future__ import annotations
import os
import contextlib
import logging
from typing import Generator

logger = logging.getLogger(__name__)

def _get_dsn() -> dict:
    host = os.environ.get("CONFIGURATOR_DB_HOST", "")
    port = os.environ.get("CONFIGURATOR_DB_PORT", "5432")
    name = os.environ.get("CONFIGURATOR_DB_NAME", "")
    user = os.environ.get("CONFIGURATOR_DB_USER", "")
    password = os.environ.get("CONFIGURATOR_DB_PASSWORD", "")
    sslmode = os.environ.get("CONFIGURATOR_DB_SSLMODE", "require")
    connect_timeout = int(os.environ.get("CONFIGURATOR_DB_CONNECT_TIMEOUT", "10"))

    if not host or not name or not user:
        raise EnvironmentError("configurator_sot_not_configured")

    return dict(host=host, port=int(port), dbname=name, user=user,
                password=password, sslmode=sslmode, connect_timeout=connect_timeout)

def _open_readonly_conn():
    from app.api.db_pool import get_conn, put_conn
    statement_timeout = int(os.environ.get("CONFIGURATOR_DB_STATEMENT_TIMEOUT_MS", "30000"))
    conn = get_conn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET statement_timeout = {statement_timeout}")
    except Exception:
        put_conn(conn, discard=True)
        raise
    return conn


@contextlib.contextmanager
def readonly_cursor(conn=None) -> Generator:
    from app.api.db_pool import put_conn
    owned = conn is None
    try:
        if owned:
            conn = _open_readonly_conn()
        with conn.cursor() as cur:
            yield cur
        if owned:
            conn.rollback()
            put_conn(conn)
    except EnvironmentError:
        if owned and conn:
            put_conn(conn, discard=True)
        raise
    except Exception as exc:
        safe_msg = type(exc).__name__
        logger.error("DB error: %s: %s", safe_msg, exc)
        if owned and conn:
            put_conn(conn, discard=True)
        raise RuntimeError(f"configurator_sot_connection_failed: {safe_msg}") from exc

def test_connection() -> dict:
    """Returns a status dict. Never raises — catches all errors."""
    try:
        with readonly_cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SHOW transaction_read_only")
            row = cur.fetchone()
            read_only = (row and row[0] == "on")
        return {"connected": True, "read_only": read_only, "error": None}
    except EnvironmentError:
        return {"connected": False, "read_only": False, "error": "configurator_sot_not_configured"}
    except Exception as exc:
        return {"connected": False, "read_only": False, "error": str(exc)}
