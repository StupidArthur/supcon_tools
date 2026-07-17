import sqlite3
db = r'C:\Users\yuzechao\.local\share\mimocode\mimocode.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()
ids = [
  'ses_0bf96131bffeUuJT8SQ1Yf39Wt',
  'ses_0bf9612bdffeJBETFfIZNtk5UO',
  'ses_0bf961278ffefZgqysQqR0ewJS',
  'ses_0a60ca0e9ffe0tIpg2jXIM56FC',
  'ses_0bf961323ffejdCyYvXfu18bgE',
  'ses_0bf96131bffeUuJT8SQ1Yf39Wt',
]
for sid in ids:
    cur.execute("SELECT id, title FROM session WHERE id=?", (sid,))
    r = cur.fetchone()
    print(sid[:25], '->', r)