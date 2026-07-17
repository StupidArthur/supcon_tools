import sqlite3, json, re
from collections import Counter

db = r'C:\Users\yuzechao\.local\share\mimocode\mimocode.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()

PROJ = '35adff5b-94b8-4dac-872a-20582729ffa8'

# Count "look"-style intents per session
cur.execute("""SELECT m.session_id, m.time_created,
                      substr(json_extract(m.data, '$.content'), 1, 150)
               FROM message m JOIN session s ON s.id = m.session_id
               WHERE s.project_id = ?
                 AND s.title NOT LIKE 'checkpoint-writer:%'
                 AND json_extract(m.data, '$.role') = 'user'
               ORDER BY m.time_created""", (PROJ,))
rows = cur.fetchall()
print('User prompt titles by session:')
for sid, t, c in rows:
    print(f'[{sid[:20] if sid else "?"}...] {(c or "")[:120]!r}')

# Detect repeated tool patterns: read same file repeatedly
print()
print('=== Files Read repeatedly (>=3 times in same or different sessions) ===')
cur.execute("""SELECT json_extract(p.data, '$.state.input') as inp
               FROM message m JOIN part p ON p.message_id = m.id
               JOIN session s ON s.id = m.session_id
               WHERE s.project_id = ?
                 AND s.title NOT LIKE 'checkpoint-writer:%'
                 AND json_extract(p.data, '$.type') = 'tool'
                 AND json_extract(p.data, '$.tool') IN ('Read','read')
                 AND json_extract(m.data, '$.role') = 'assistant'""", (PROJ,))
file_counter = Counter()
for (inp,) in cur.fetchall():
    try:
        d = json.loads(inp) if isinstance(inp, str) else inp
        fp = d.get('file_path','')
        if fp:
            file_counter[fp] += 1
    except: pass
for fp, n in file_counter.most_common(25):
    if n >= 3:
        print(f'{n:3d}  {fp}')

print()
print('=== Bash command prefix frequency ===')
cur.execute("""SELECT json_extract(p.data, '$.state.input') as inp
               FROM message m JOIN part p ON p.message_id = m.id
               JOIN session s ON s.id = m.session_id
               WHERE s.project_id = ?
                 AND s.title NOT LIKE 'checkpoint-writer:%'
                 AND json_extract(p.data, '$.type') = 'tool'
                 AND json_extract(p.data, '$.tool') IN ('Bash','bash')
                 AND json_extract(m.data, '$.role') = 'assistant'""", (PROJ,))
cmd_counter = Counter()
for (inp,) in cur.fetchall():
    try:
        d = json.loads(inp) if isinstance(inp, str) else inp
        cmd = d.get('command','')[:120]
        cmd_counter[cmd] += 1
    except: pass
for cmd, n in cmd_counter.most_common(25):
    if n >= 2:
        print(f'{n:3d}  {cmd[:140]}')

# Look for "git" related patterns
print()
print('=== git command prefix frequency (project) ===')
git_counter = Counter()
for cmd, n in cmd_counter.items():
    if 'git ' in cmd or cmd.startswith('git'):
        git_counter[cmd[:140]] += n
for cmd, n in git_counter.most_common(15):
    print(f'{n:3d}  {cmd}')