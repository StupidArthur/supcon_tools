import json, glob, os

all_results = {}
for d in sorted(glob.glob('output/automation_ua2_*_20260715_*')):
    f = os.path.join(d, 'ua2-result.json')
    if not os.path.exists(f): continue
    r = json.load(open(f))
    bn = os.path.basename(d)
    parts = bn.split('_')
    ch_code = parts[2]
    if ch_code.startswith('ua'):
        n = ch_code[2:]
        if len(n) == 2: chapter = 'UA-' + n[0] + '-' + n[1]
        elif len(n) == 3: chapter = 'UA-' + n[0] + '-' + n[1:]
        else: chapter = ch_code
    else: chapter = ch_code
    cases = r.get('caseResults', [])
    fails = [(c['caseId'], c['status']) for c in cases if c['status'] in ('FAIL','ERROR','BLOCKED')]
    all_results[chapter] = {
        'status': r.get('status',''),
        'pass': r.get('passCount',0),
        'fail': r.get('failCount',0),
        'error': r.get('errorCount',0),
        'blocked': r.get('blockedCount',0),
        'total': len(cases),
        'fails': fails,
    }

lines = []
lines.append('# UA batch run report (2026-07-15)')
lines.append('')
lines.append('## Summary')
tp=tf=te=tb=tt=0
for ch in sorted(all_results):
    r = all_results[ch]
    tp+=r['pass']; tf+=r['fail']; te+=r['error']; tb+=r['blocked']; tt+=r['total']
lines.append('Total: %d  PASS: %d  FAIL: %d  ERROR: %d  BLOCKED: %d' % (tt,tp,tf,te,tb))
lines.append('')
lines.append('## By chapter')
lines.append('| Ch | Total | PASS | FAIL | ERR | BLK |')
lines.append('|---|---|---|---|---|---|')
for ch in sorted(all_results):
    r = all_results[ch]
    lines.append('| %s | %d | %d | %d | %d | %d |' % (ch, r['total'], r['pass'], r['fail'], r['error'], r['blocked']))
lines.append('| **Total** | **%d** | **%d** | **%d** | **%d** | **%d** |' % (tt,tp,tf,te,tb))
lines.append('')
lines.append('## FAIL/ERROR/BLOCKED details')
for ch in sorted(all_results):
    r = all_results[ch]
    if r['fails']:
        lines.append('### %s' % ch)
        for cid, status in r['fails']:
            lines.append('- %s: %s' % (cid, status))
        lines.append('')

lines.append('## Notes')
lines.append('- UA-1-3 all FAIL: rt_changed product bug (mock values change but TPT RT does not reflect), Class A')
lines.append('- UA-1-4: old result (shared mocks not running), code fixed, pending rerun')
lines.append('- UA-1-6: 02/07 fixed (catch TptAPIError), 06 FAIL may be product bug')
lines.append('- UA-2-1 has 18 BLOCKED: baseline issue')
lines.append('- UA-3-4 has 5 BLOCKED: history verify fixed, may need longer wait')
lines.append('- 115 PARTIAL exploratory cases not run (runner skips by default)')

with open('output/overnight_report.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Report written to output/overnight_report.md')
print('\n'.join(lines[:25]))
