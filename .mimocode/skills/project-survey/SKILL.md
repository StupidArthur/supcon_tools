---
name: project-survey
description: "Map an unfamiliar subdirectory of F:\\github\\supcon_tools at the start of a session by spawning 3 parallel `explore` subagents (surface map / wiring & deps / cross-project diff). Use when the user says 看下X / 看一下X / 调研X / 了解X / check out the X code, and X is one of tpt_api, ua_test_gui, ua_test_harness, ua_tpt_loop, ua_tpt_manager, or another non-trivial subdir. Do NOT use for single-file reads, for subdirs already mapped in a prior session of the same project (read checkpoint.md §6 + §7 first), or for editing/implementing work."
---

# Project survey (3-angle parallel explore)

When the user opens a session with an inspection-style intent and a non-trivial
subdirectory as the target, the proven pattern in this project is to fan out
3 parallel `explore` subagents and synthesize their reports into a single
mapping. Do this **once** at session start; subsequent sessions reuse the
checkpointed mapping.

## When to trigger

User phrases that have historically meant "please map this subdir":
- "看下X" / "看一下X" / "看看X" / "查看X下的代码"
- "调研一下X" / "摸清X的现状"
- "X 这块我不熟, 你介绍一下" / "X 是什么"
- Followed by an implementation task that requires understanding X first.

Do **not** trigger when:
- X is a single file (just `Read` it).
- X is a subdir you already mapped in this session or the immediately prior
  session of this project (consult `MEMORY.md` and the previous
  `checkpoint.md` §6 / §7 first — re-explore is wasteful).
- The user gave a direct implementation task without first asking for context.

## The 3 angles

Spawn exactly 3 `explore` subagents in a single message (parallel). Keep
their prompts tight; each agent should return ≤200 lines of structured text.

### Angle 1 — Surface map
**Prompt template:**
> Map the public surface of `F:\github\supcon_tools\<X>\`. Return:
> 1. File-by-file: filename, purpose (1 sentence), exported symbols
>    (functions / types / constants) with line numbers.
> 2. Test files: count + naming pattern + what they cover.
> 3. Examples / demos: location + how they're invoked.
> 4. README / docs: location + 1-line summary of what they cover.
>
> Do NOT summarize dependencies or call-sites — Angle 2 owns that.
> Output as Markdown tables.

### Angle 2 — Wiring & dependencies
**Prompt template:**
> For `F:\github\supcon_tools\<X>\` (and `<X>/go.mod` / `<X>/pyproject.toml`
> / `<X>/requirements*.txt` if present), return:
> 1. Module declaration: language + module path + runtime version + external
>    deps (with versions).
> 2. Internal cross-references within X (import graph summary, 1 line per edge).
> 3. External callers inside F:\github\supcon_tools (other subdirs that
>    import / spawn / depend on X) — list each caller + how it consumes X.
> 4. Auto-generated / synced files: any `*_full.go`, `*_pb.go`, files with
>    `// Code generated` headers, or files explicitly marked as
>    synced-from-elsewhere (cite the source-of-truth doc if found).
> 5. Test fixtures / golden files / mock servers.
>
> Do NOT re-list exported symbols — Angle 1 owns that.

### Angle 3 — Cross-project diff
**Prompt template:**
> `F:\github\supcon_tools\<X>\` likely consolidates / replaces legacy code
> elsewhere in the repo. Find the legacy sites by grepping the rest of
> `F:\github\supcon_tools\` for similar function names / endpoint paths /
> import paths. Return:
> 1. Legacy sites (paths + 1-line description of each).
> 2. For each: which methods / fields / endpoints overlap with X, and any
>    drift (param renamed, type changed, behavior tightened/loosened,
>    code/status tolerance added/dropped, error code added/removed).
> 3. Known platform-side quirks preserved across sites (cookie typos,
>    form-field typos, intentional mis-spellings) — call these out so we
>    don't "fix" them later.
> 4. Any caller still bound to the legacy path (e.g. `USER_MANAGER/app.go`
>    still importing the old `internal/api`) and what's blocking the
>    migration (missing type re-export, etc.).
>
> Use `grep -r` from `F:\github\supcon_tools\` (excluding `.mimocode/`,
> `node_modules/`, `__pycache__/`, `output/`, `.git/`).

## Synthesis (main agent)

After the 3 agents return, write a single short summary (≤300 words) to the
user. Then decide:

- **No plan needed** (pure inspection): the user only said "看下". Reply
  with the surface map + the 2-3 most interesting findings. Do NOT spawn
  the plan mode unless the user asks.
- **User signals a follow-up implementation**: spawn ONE more focused
  `explore` (or a `general`) agent to confirm the gap before exiting plan
  mode with `plan_exit`. Do NOT skip this confirmation step — the parallel
  survey is meant to inform a plan, not bypass one.

## Stopping condition

Stop when one of:
- User says "好, 知道了" / "够了" / explicit dismissal.
- User specifies what to do next (drill into angle X, write plan, implement).
- 3 turns after survey delivery with no further direction → politely check
  in once and stop.

## Known subdirs this works for (verified pattern)

`[ses_0bf96131b]` ua_player, ua_tpt_loop, supcon_io (3 dirs in one batch)
`[ses_0bf9612bd]` ua_tpt_manager
`[ses_0bf961278]` ua_player / tpt_api (3-angle across 3+ sessions)
`[ses_0a60ca0e9ffeo0tIpg2jXIM56FC]` tpt_api/go (this session, 2026-07-13)

For unfamiliar subdirs, the same 3-angle split is the right default.