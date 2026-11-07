import sqlite3

conn = sqlite3.connect("file:runtime/instances/daily/data/sql/db/agent.db?mode=ro", uri=True)
cursor = conn.cursor()
cursor.execute("SELECT id, created_at, thoughts, actions, results FROM ticks ORDER BY created_at DESC LIMIT 21;")
rows = cursor.fetchall()
print(f"Loaded {len(rows)} ticks.")

chars_total = 0
for r in rows:
    t_id, created_at, thoughts, actions, results = r
    entry_len = len(str(thoughts or "")) + len(str(actions or "")) + len(str(results or ""))
    chars_total += entry_len

print(f"Total raw tick chars: {chars_total}")
for i, r in enumerate(rows[:5]):
    t_id, created_at, thoughts, actions, results = r
    print(f"Tick {i} ({t_id}): thoughts={len(str(thoughts or ''))}, actions={len(str(actions or ''))}, results={len(str(results or ''))}")
