import sqlite3

conn = sqlite3.connect("runtime/instances/daily/data/sql/db/agent.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)
for t in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"{t}: {cursor.fetchone()[0]}")
