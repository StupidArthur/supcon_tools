---
name: tpt-verify-no-envvars
description: "Run verify / debug scripts against the TPT admin / datahub test environment WITHOUT using shell env vars (DATAHUB_BASE_URL / DATAHUB_PASSWORD / DATAHUB_USER / TPT_*). Read creds from F:\\github\\supcon_tools\\env.json (gitignored) instead. Use whenever the user asks to 'verify X', 'test X against the platform', 'run verify_tag_value.py', 'login and check Y', or any script that needs the test env credentials. Hard requirement: USER MANDATE 'No env vars for config' is in MEMORY.md ## Rules and the assistant has slipped 8+ times in the past 30 days — always go through env.json."
---

# TPT / datahub verify without env vars

Hard rule (USER MANDATE, in `MEMORY.md` ## Rules):

> **No env vars for config**: scripts read connection info
> (`base_url` / `username` / `password` / `local_ip` / `tenantId`)
> from `F:\github\supcon_tools\env.json` (gitignored, not committed),
> **NOT** from `os.environ` or `KEY=VALUE` shell prefixes.

Why: env vars are fragile (the main agent's shell may not have them set, so
the verify silently reads empty / wrong values and you waste a debug round),
and they're unnecessary — the SUT creds are not sensitive.

## Step 1 — Confirm env.json exists and is shaped correctly

```bash
# read without printing the password
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'F:\github\supcon_tools\env.json').read_text(encoding='utf-8'))
required = ['baseUrl', 'username', 'password', 'tenantId', 'localIp']
missing = [k for k in required if k not in d]
print('keys ok' if not missing else f'missing: {missing}')
print('baseUrl =', d.get('baseUrl'))
print('username =', d.get('username'))
print('localIp =', d.get('localIp'))
print('tenantId =', repr(d.get('tenantId', '')))
"
```

If `keys ok` is not printed, stop and ask the user — do NOT invent credentials
and do NOT fall back to env vars.

## Step 2 — Load creds inside the script (Python)

```python
import json, pathlib, sys
from tpt_api import AlgAPI, datahub  # adjust import as needed

CFG = json.loads(
    pathlib.Path(r'F:\github\supcon_tools\env.json').read_text(encoding='utf-8')
)

api = AlgAPI(CFG['baseUrl'], timeout=60.0)
api.login(CFG['username'], CFG['password'], tenant_id=CFG.get('tenantId') or None)
```

Do **NOT** wrap this with `DATAHUB_PASSWORD=... python - <<'PY'` — that's
exactly what the rule forbids.

## Step 3 — Bash invocation

The right shell incantation is plain:

```bash
cd "F:/github/supcon_tools/<subdir>" && python verify_xxx.py
```

or for one-off inline probes:

```bash
cd "F:/github/supcon_tools" && python - <<'PY'
import json, pathlib
from tpt_api import AlgAPI, datahub
CFG = json.loads(pathlib.Path(r'F:\github\supcon_tools\env.json').read_text(encoding='utf-8'))
api = AlgAPI(CFG['baseUrl'], timeout=60.0)
api.login(CFG['username'], CFG['password'], tenant_id=CFG.get('tenantId') or None)
# ... verify ...
PY
```

Both forms read `env.json` inside the Python process. **No `KEY=VALUE` prefix
on the bash line, ever.**

## Step 4 — Sanity-check after running

If a verify returns an unexpected value (e.g. `getRTValue` returns `0.0` or
the old value 60s after a write), before assuming a product bug:

1. Confirm `env.json` was actually read (add `print('baseUrl =', CFG['baseUrl'])`).
2. Confirm the `baseUrl` is **without** a trailing `/tpt-admin/` path —
   see MEMORY.md ## Patterns: "Base URL construction: TPT admin URLs should
   not include `/tpt-admin/` in base_url as it duplicates in LoginPath."
3. Confirm the `username` is the right tenant admin (the user has multiple
   roles in some envs).

## Anti-patterns (must NOT emit)

These have appeared in past sessions and are the things this skill exists to
prevent:

```bash
# WRONG — DATAHUB_PASSWORD env var
DATAHUB_BASE_URL=http://... DATAHUB_USER=admin DATAHUB_PASSWORD=123456 \
    python - <<'PY' ...
```

```bash
# WRONG — creds inlined in shell (still env-var style, plus leaks to history)
BASE_URL=http://... PASSWORD=123456 python test_x.py
```

```bash
# WRONG — creds inlined in heredoc body (leaks to git if pasted into a file)
python - <<'PY'
api.login("admin", "123456", ...)
PY
```

```python
# WRONG — read from os.environ
import os
api.login(os.environ['TPT_USER'], os.environ['TPT_PASS'])
```

The Python inside the heredoc may freely use `env.json`; only the **shell**
must stay clean.

## When env.json is the wrong tool

- **CI / one-shot scripts in a clean checkout**: copy `env.json.template`
  (if you create one) and fill in. Don't bypass the file.
- **Public distribution**: the exe must not ship `env.json` either — make it
  read from `%APPDATA%\ua_tpt_manager\config.json` (or per-tool equivalent)
  with `env.json` as the developer-local override.

## Evidence this rule keeps getting violated

`[ses_0bf961278ffefZgqysQqR0ewJS]` ×6+ invocations of
`DATAHUB_PASSWORD=... DATAHUB_BASE_URL=... DATAHUB_USER=... python - <<'PY'`
on 2026-07-12/13, while MEMORY.md already contained the USER MANDATE for
"no env vars". Each violation wasted a round of debugging when the script
silently ran with a missing/empty value.

If you catch yourself about to type `KEY=VALUE python …`, stop and rewrite
as Step 2 + Step 3 above.