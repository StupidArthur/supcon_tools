import json, glob, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from collections import defaultdict

all_cases = {}
for d in sorted(glob.glob('output/automation_ua2_*_20260715_1*')):
    f = os.path.join(d, 'ua2-result.json')
    if not os.path.exists(f): continue
    r = json.load(open(f, encoding='utf-8'))
    bn = os.path.basename(d)
    parts = bn.split('_')
    ch_code = parts[2]
    if ch_code.startswith('ua'):
        n = ch_code[2:]
        if len(n) == 2: chapter = 'UA-' + n[0] + '-' + n[1]
        elif len(n) == 3: chapter = 'UA-' + n[0] + '-' + n[1:]
        else: chapter = ch_code
    else: chapter = ch_code
    for c in r.get('caseResults', []):
        cid = c['caseId']
        # Read stderr log
        stderr_path = os.path.join(d, 'cases', cid, 'stderr.log')
        stderr = ''
        if os.path.exists(stderr_path):
            try:
                stderr = open(stderr_path, encoding='utf-8', errors='replace').read()[:800]
            except:
                stderr = ''
        all_cases[cid] = {
            'chapter': chapter,
            'status': c['status'],
            'duration': c.get('durationMs', 0),
            'stderr': stderr,
        }

# Print non-PASS cases grouped by chapter
for cid in sorted(all_cases):
    c = all_cases[cid]
    if c['status'] in ('FAIL', 'ERROR', 'BLOCKED'):
        print('=== %s [%s] %dms ===' % (cid, c['status'], c['duration']))
        if c['stderr']:
            # Extract key error line
            for line in c['stderr'].split('\n'):
                line = line.strip()
                if line and ('Error' in line or 'error' in line or 'FAIL' in line or 'BLOCKED' in line or 'AssertFail' in line or 'timeout' in line or 'BaselineError' in line or 'Traceback' in line or 'raise' in line):
                    print('  ', line[:200].encode('ascii', 'replace').decode('ascii'))
        print()
