import psycopg2, os

conn = psycopg2.connect(
    host=os.environ.get("CONFIGURATOR_DB_HOST"),
    port=int(os.environ.get("CONFIGURATOR_DB_PORT", 5432)),
    dbname=os.environ.get("CONFIGURATOR_DB_NAME"),
    user=os.environ.get("CONFIGURATOR_DB_USER"),
    password=os.environ.get("CONFIGURATOR_DB_PASSWORD"),
    sslmode="disable"
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("""
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = current_database()
    AND pid <> pg_backend_pid()
    AND state IN ('idle', 'idle in transaction', 'idle in transaction (aborted)')
""")
killed = cur.rowcount
print(f"Killed {killed} stale connections")
conn.close()
