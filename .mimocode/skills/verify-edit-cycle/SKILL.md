---
name: verify-edit-cycle
description: "After editing code in F:\\github\\supcon_tools, run the right verification command for the language + directory. Maps Go edits → `go build ./...` (+ targeted `go test`), Python edits → `pytest tests/ -q | tail -N`, frontend edits → `npm run build`. Use whenever the assistant just produced an Edit / Write to a .go / .py / .ts(x) / .vue file and the next action is a self-check. Do NOT use before edits, for pure plan-mode sessions with no edits, or for edits in unrelated submodules (data_factory_server, review3 — see MEMORY.md ## Rules)."
---

# Verify-after-edit cycle

When you finish editing code, **always** run the matching check command
**before** reporting the work is done. This skill encodes the project-specific
map of "what to run after editing what" so you don't have to rediscover it
each time.

## The map

| Edited file pattern | Run | Notes |
|---|---|---|
| `tpt_api/go/*.go` (or `go.mod`) | `cd "F:/github/supcon_tools/tpt_api/go" && go build ./... 2>&1` | stdlib-only module, fast. If build OK and the file has tests, also run the package's `go test -count=1 ./<pkg>` (e.g. `go test ./internal/adapters/pyworker/ -count=1 -v` for the Wails worker). |
| `tpt_api/python/tpt_api/*.py` | `cd "F:/github/supcon_tools/tpt_api/python" && python -m pytest tests/ -q 2>&1 | tail -10` | Tests live in `tpt_api/python/tests/`. |
| `tpt_api/python/examples/*.py` (the verify scripts) | `python <script>` against `env.json` — see `tpt-verify-no-envvars` skill | Don't run with env-var creds. |
| `ua_tpt_loop/**/*.py` | `cd "F:/github/supcon_tools/ua_tpt_loop" && python -m pytest tests/ -q 2>&1 | tail -5` | 8 invocations of this exact prefix in past 30 days. |
| `ua_test_gui/internal/**/*.go` | `cd "F:/github/supcon_tools/ua_test_gui" && go build ./...` (Wails requires `wails generate module` after editing `internal/app.go` or service interfaces — see step 2 below) | |
| `ua_test_gui/frontend/src/**/*.{ts,tsx,vue}` | `cd "F:/github/supcon_tools/ua_test_gui/frontend" && npm run build` | 7 invocations in past 30 days. Tail the last 30 lines. |
| `ua_player/**/*.py` | `cd "F:/github/supcon_tools/ua_player" && python -c "import ast; [ast.parse(open(p, encoding='utf-8').read()) for p in __import__('glob').glob('*.py')]; print('syntax OK')"` + smoke-test against a real `asyncua` client | No formal pytest; rely on syntax check + smoke. |
| `ua_mocker/**/*.py` | Same as ua_player (syntax + smoke spawn). | |
| `qt5-version/cli/**/*.py` | See `.mimocode/skills/cli-tool/SKILL.md` for the CLI conventions; verify by running the entry point with `--help` and confirming `rich` / `questionary` import. | |

## Step 1 — Run the right command

Pick the row that matches what you just edited. Run it. **Tail the output**
— don't let long pytest traces flood the context.

```bash
# pattern for tail-of-pytest
cd "<dir>" && python -m pytest tests/ -q 2>&1 | tail -10
```

```bash
# pattern for go build
cd "<dir>" && go build ./... 2>&1
```

```bash
# pattern for frontend build
cd "F:/github/supcon_tools/ua_test_gui/frontend" && npm run build 2>&1 | tail -30
```

If the build fails, **fix the failure before moving on**. Don't say "I'll
fix that in the next turn" — the user will catch it and you'll lose trust.

## Step 2 — Wails special case

If you edited `ua_test_gui/internal/app.go` or changed any service
interface / struct / method signature, Wails bindings need regeneration
**before** the frontend will compile cleanly:

```bash
cd "F:/github/supcon_tools/ua_test_gui" && wails generate module
```

Then re-run the frontend `npm run build` to confirm the regenerated
bindings line up with what the frontend imports.

## Step 3 — Pytest pattern that doesn't bite back

Two flavors of pytest tail are used in past sessions; pick the right one:

- `| tail -5` for a quick "passed / failed" line (use most of the time).
- `| tail -10` when you want to see the last few failure traceback headers.
- `| tail -50` when debugging — only after a quick tail -5 already showed red.

For targeted debugging of a single test:

```bash
cd "<dir>" && python -m pytest tests/<file>.py::test_<name> -v 2>&1 | tail -20
```

## Step 4 — Report the result

End your turn with one of:

- **All green:** say so explicitly. State the count
  (`pytest 178 passed`, `go build ./... OK`, `npm run build OK (X.XXs)`).
- **Red:** paste the failing line / first error. Don't paraphrase failures
  — they're the user's signal to fix things.

## Stopping condition

Stop after the first verification round. Don't loop on retries past the
second failure without asking the user — per `AGENTS.md` §1 / §2:
**don't paper over environment / tool problems with try/except or by
swapping the protocol.** If the test fails because the platform / mocker
genuinely misbehaves, **record it truthfully** (FAIL / BLOCKED / CLEANUP_FAILED)
in `nightly-report.md` / `report.json` / NDJSON events and surface to the
user. Do NOT add `try/except` to make the case pass.

## Cross-references

- `AGENTS.md` §1 — don't route around env / tool problems.
- `AGENTS.md` §2 — case 怎么写就怎么实现; failed cases are valid output.
- `MEMORY.md` ## Rules "No subagent implementation for UA-2 refactor" —
  cheap-agent work must NOT be committed by the sub-agent itself; main agent
  reviews scope + commits. **verify-edit-cycle** is meant for the **main
  agent's own** edits; the cheap-agent verification flow goes through
  `docs/talk-main.md` instead.