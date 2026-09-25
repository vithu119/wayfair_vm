import psycopg2, os, bcrypt

password = b'vithusali@1999'
hashed = bcrypt.hashpw(password, bcrypt.gensalt()).decode()

conn = psycopg2.connect(
    host=os.environ['CONFIGURATOR_DB_HOST'],
    port=os.environ['CONFIGURATOR_DB_PORT'],
    dbname=os.environ['CONFIGURATOR_DB_NAME'],
    user=os.environ['CONFIGURATOR_DB_USER'],
    password=os.environ['CONFIGURATOR_DB_PASSWORD'],
    sslmode='disable'
)
cur = conn.cursor()
cur.execute("UPDATE blos.app_users SET hashed_password = %s WHERE username = 'vithusali'", (hashed,))
conn.commit()
print('Password updated')
