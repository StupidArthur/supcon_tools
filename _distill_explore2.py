import sqlite3, json
from collections import Counter

db = r'C:\Users\yuzechao\.local\share\mimocode\mimocode.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()

# Find main user sessions in this project
PROJ = '35adff5b-94b8-4dac-872a-20582729ffa8'

print('=== REAL USER SESSIONS IN PROJECT ===')
# Real sessions are not "checkpoint-writer:" - filter
cur.execute("""SELECT id, title, time_created, time_updated FROM session
               WHERE project_id = ? AND title NOT LIKE 'checkpoint-writer:%'
               ORDER BY time_created DESC""", (PROJ,))
for r in cur.fetchall():
    print(r)

print()
print('=== TOOL USAGE BY USER (last 30d, assistant main only) ===')
# 30 days back
cutoff = 1783609744274 - 30*24*3600*1000
cur.execute("""SELECT json_extract(p.data, '$.tool') as tool, count(*) as n
               FROM message m JOIN part p ON p.message_id = m.id
               WHERE json_extract(m.data, '$.role')='assistant'
                 AND m.agent_id='main'
                 AND json_extract(p.data, '$.type')='tool'
                 AND m.time_created > ?
               GROUP BY tool ORDER BY n DESC""", (cutoff,))
for r in cur.fetchall():
    print(r)

print()
print('=== TOP TOOL INPUT PREVIEWS (main agent, last 30d) ===')
cur.execute("""SELECT json_extract(p.data, '$.tool') as tool,
                      substr(json_extract(p.data, '$.state.input'), 1, 250) as inp,
                      count(*) as n
               FROM message m JOIN part p ON p.message_id = m.id
               WHERE json_extract(m.data, '$.role')='assistant'
                 AND m.agent_id='main'
                 AND json_extract(p.data, '$.type')='tool'
                 AND m.time_created > ?
               GROUP BY tool, inp ORDER BY n DESC LIMIT 60""", (cutoff,))
for r in cur.fetchall():
    print(r)

print()
print('=== USER TURNS WITH REPEAT PHRASES (last 30d) ===')
patterns = ['again','every time','like last time','the usual','repeat','same as before','每次','又','重复','按之前的']
for pat in patterns:
    cur.execute("""SELECT session_id, substr(json_extract(m.data,'$.content'),1,200)
                   FROM message m
                   WHERE json_extract(m.data, '$.role')='user'
                     AND m.time_created > ?
                     AND json_extract(m.data, '$.content') LIKE ?""", (cutoff, f'%{pat}%'))
    rows = cur.fetchall()
    if rows:
        print(f'-- pattern: {pat!r} ({len(rows)} hits)')
        for r in rows[:3]:
            print(' ', r)