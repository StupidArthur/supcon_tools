import sqlite3, json, os, sys

db = r'C:\Users\yuzechao\.local\share\mimocode\mimocode.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()

# Schema
print('=== SCHEMA ===')
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
for n, s in cur.fetchall():
    print(f'-- {n} --')
    print(s[:800] if s else '')
    print()

# Sessions recent (last 30 days)
print('=== RECENT SESSIONS (last 30d) ===')
cur.execute("SELECT id, project_id, directory, title, time_created, time_updated FROM session ORDER BY time_created DESC LIMIT 50")
for row in cur.fetchall():
    print(row)

# Counts
print()
print('=== COUNTS ===')
for t in ['session','message','part','task','task_event','actor_registry']:
    try:
        cur.execute(f'SELECT count(*) FROM {t}')
        print(t, cur.fetchone()[0])
    except Exception as e:
        print(t, 'ERR', e)