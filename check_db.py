import os
import psycopg2

conn = psycopg2.connect(
    host=os.environ['DB_HOST'],
    port=os.environ['DB_PORT'],
    dbname=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD']
)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM parse_sessions WHERE status = 'success'")
print(f"Sessions: {cur.fetchone()[0]}")
conn.close()
