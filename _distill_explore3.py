import sqlite3, json, re
from collections import Counter, defaultdict

db = r'C:\Users\yuzechao\.local\share\mimocode\mimocode.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()

PROJ = '35adff5b-94b8-4dac-872a-20582729ffa8'

# Look at full user turns in project (not checkpoint-writer)
cur.execute("""SELECT m.session_id, m.id, json_extract(m.data, '$.content')
               FROM message m JOIN session s ON s.id = m.session_id
               WHERE s.project_id = ?
                 AND s.title NOT LIKE 'checkpoint-writer:%'
                 AND json_extract(m.data, '$.role') = 'user'
               ORDER BY m.time_created""", (PROJ,))
rows = cur.fetchall()
print(f'Total user turns in project: {len(rows)}')

# Print all user prompts (truncated)
print()
print('=== USER PROMPTS ===')
for sid, mid, content in rows:
    c = (content or '')[:300].replace('\n',' / ')
    print(f'[{sid}] {c}')

# Look at assistant text content summary - what does the assistant typically do at start of session?
print()
print('=== FIRST ASSISTANT MESSAGE OF EACH USER SESSION (text only) ===')
cur.execute("""SELECT s.id, m.id, m.time_created, json_extract(p.data,'$.text')
               FROM session s
               JOIN message m ON m.session_id = s.id
               JOIN part p ON p.message_id = m.id
               WHERE s.project_id = ?
                 AND s.title NOT LIKE 'checkpoint-writer:%'
                 AND json_extract(m.data, '$.role') = 'assistant'
                 AND json_extract(p.data, '$.type') = 'text'
               ORDER BY s.time_created, m.time_created""", (PROJ,))
last_sid = None
first_count = Counter()
for sid, mid, t, txt in cur.fetchall():
    if sid != last_sid:
        last_sid = sid
        snippet = (txt or '')[:200].replace('\n',' / ')
        print(f'-- {sid} --')
        print(snippet)
        print()