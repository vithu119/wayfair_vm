from __future__ import annotations
import os
import time
import threading
import logging
import psycopg2
from psycopg2 import pool

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_pool: pool.ThreadedConnectionPool | None = None


def _get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _lock:
        if _pool is not None:
            return _pool
        host = os.environ.get("CONFIGURATOR_DB_HOST", "")
        port = int(os.environ.get("CONFIGURATOR_DB_PORT", "5432"))
        name = os.environ.get("CONFIGURATOR_DB_NAME", "")
        user = os.environ.get("CONFIGURATOR_DB_USER", "")
        password = os.environ.get("CONFIGURATOR_DB_PASSWORD", "")
        sslmode = os.environ.get("CONFIGURATOR_DB_SSLMODE", "disable")
        if not host or not name or not user:
            raise EnvironmentError("CONFIGURATOR_DB_* env vars not configured")
        maxconn = int(os.environ.get("DB_POOL_MAX", "30"))
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=maxconn,
            host=host, port=port, dbname=name, user=user,
            password=password, sslmode=sslmode,
            connect_timeout=10,
        )
        logger.info("DB connection pool created (max=%d)", maxconn)
        return _pool


def _is_alive(conn) -> bool:
    if conn.closed:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except Exception:
        return False


def get_conn(retries: int = 12, delay: float = 0.5):
    """Acquire a connection, retrying on pool exhaustion or server connection limit."""
    p = _get_pool()
    for attempt in range(retries):
        try:
            conn = p.getconn()
            if _is_alive(conn):
                return conn
            # Stale connection (server dropped it) — discard and try a fresh one
            p.putconn(conn, close=True)
            continue
        except (pool.PoolError, psycopg2.OperationalError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
    raise pool.PoolError("connection pool exhausted")


def put_conn(conn, discard=False):
    try:
        _get_pool().putconn(conn, close=discard)
    except Exception:
        pass
