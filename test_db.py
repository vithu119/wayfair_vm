import psycopg2, os

host = os.environ.get("CONFIGURATOR_DB_HOST", "")
port = os.environ.get("CONFIGURATOR_DB_PORT", "5432")
name = os.environ.get("CONFIGURATOR_DB_NAME", "")
user = os.environ.get("CONFIGURATOR_DB_USER", "")
password = os.environ.get("CONFIGURATOR_DB_PASSWORD", "")

print(f"Host: {host}")
print(f"Port: {port}")
print(f"DB: {name}")
print(f"User: {user}")

try:
    conn = psycopg2.connect(
        host=host, port=int(port), dbname=name, user=user,
        password=password, sslmode='disable', connect_timeout=10
    )
    cur = conn.cursor()
    cur.execute("SELECT version()")
    print("DB connected:", cur.fetchone()[0])
    conn.close()
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
