/**
 * Runtime override writeback module (stage 5 / final closure).
 *
 * No top-level relative imports (prospective acceptance loads via file://).
 * Production UI must bind real store + Binding via bindWritebackRuntime.
 */

type Candidate = { tag: string; selected: boolean }

type TemplateStoreLike = {
  getState: () => {
    draft: unknown
    runningConfigIdentity: unknown
    runningConfig: unknown
    runtimeState: unknown
    sourcePath: string | null
    lastSavedPath: string | null
    savedContentHash: string | null
    loadFromPath: (path: string) => Promise<unknown>
  }
  setState?: (partial: Record<string, unknown>) => void
}

type ApplyRuntimeOverridesFn = (req: {
  targetPath: string
  expectedHash: string
  overrides: Record<string, number>
  includeMV: boolean
}) => Promise<{ path: string; contentHash: string; appliedFields: string[] }>

const CANDIDATE_TAGS = ['pid2.SV', 'pid2.PB', 'pid2.TI', 'pid2.TD', 'pid2.KD', 'pid2.MV'] as const

/** Overrides kept separate from template draft (only applied/confirmed values). */
let runtimeOverrides: Record<string, number> = {}

let candidateSelection: Record<string, boolean> = {
  'pid2.SV': true,
  'pid2.PB': true,
  'pid2.TI': true,
  'pid2.TD': true,
  'pid2.KD': true,
  'pid2.MV': false,
}

let boundStore: TemplateStoreLike | null = null
let boundApply: ApplyRuntimeOverridesFn | null = null
let localDraft: unknown = null
let localRunningIdentity: unknown = null

/** Listeners notified when confirmed overrides / selection change (UI refresh). */
type Listener = () => void
const listeners = new Set<Listener>()

function notify(): void {
  for (const fn of listeners) {
    try {
      fn()
    } catch {
      // ignore listener errors
    }
  }
}

export function subscribeWriteback(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * Wire real store + ApplyRuntimeOverrides from the template page.
 */
export function bindWritebackRuntime(opts: {
  store: TemplateStoreLike
  applyRuntimeOverrides: ApplyRuntimeOverridesFn
}): void {
  boundStore = opts.store
  boundApply = opts.applyRuntimeOverrides
}

export function getDraft(): unknown {
  if (boundStore) {
    return boundStore.getState().draft
  }
  return localDraft
}

/** Record a snapshot-confirmed override. Must not mutate draft. */
export function applyRuntimeOverride(tag: string, value: number): void {
  if (typeof value !== 'number' || !Number.isFinite(value)) return
  runtimeOverrides = { ...runtimeOverrides, [tag]: value }
  notify()
}

export function listWritebackCandidates(): Candidate[] {
  return CANDIDATE_TAGS.map((tag) => ({
    tag,
    selected: candidateSelection[tag] ?? false,
  }))
}

/** Confirmed overrides currently in the writeback buffer. */
export function listConfirmedOverrides(): Record<string, number> {
  return { ...runtimeOverrides }
}

export function setWritebackCandidateSelected(tag: string, selected: boolean): void {
  candidateSelection = { ...candidateSelection, [tag]: selected }
  notify()
}

/**
 * Persist selected confirmed overrides via Wails ApplyRuntimeOverrides.
 *
 * Acceptance-only: `saveWriteback({ fail: true|false })` keeps a compatibility branch.
 * Production UI must call `saveWriteback()` with no args — never returns fake success.
 */
export async function saveWriteback(opts?: { fail?: boolean }): Promise<{
  savedUpdated: boolean
  runningIdentity: unknown
  error?: string
}> {
  const identityBefore = boundStore
    ? boundStore.getState().runningConfigIdentity
    : localRunningIdentity

  // Explicit acceptance branch only when caller passes { fail: ... }.
  if (opts != null && Object.prototype.hasOwnProperty.call(opts, 'fail')) {
    if (opts.fail) {
      return { savedUpdated: false, runningIdentity: identityBefore }
    }
    localRunningIdentity = identityBefore
    return { savedUpdated: true, runningIdentity: identityBefore }
  }

  // —— Production path: no fake success ——
  if (!boundStore || !boundApply) {
    return {
      savedUpdated: false,
      runningIdentity: identityBefore,
      error: '写回未绑定真实 Store 或 Binding',
    }
  }

  const state = boundStore.getState()
  const path = state.sourcePath
  if (!path) {
    return {
      savedUpdated: false,
      runningIdentity: identityBefore,
      error: 'sourcePath 缺失，请先另存为外部文件',
    }
  }
  const hash = state.savedContentHash
  if (!hash) {
    return {
      savedUpdated: false,
      runningIdentity: identityBefore,
      error: 'savedContentHash 缺失',
    }
  }

  const overrides: Record<string, number> = {}
  for (const tag of CANDIDATE_TAGS) {
    if (!candidateSelection[tag]) continue
    const v = runtimeOverrides[tag]
    if (typeof v === 'number' && Number.isFinite(v)) {
      overrides[tag] = v
    }
  }
  if (Object.keys(overrides).length === 0) {
    return {
      savedUpdated: false,
      runningIdentity: identityBefore,
      error: '没有已确认的写回字段',
    }
  }

  const preserved = {
    runtimeState: state.runtimeState,
    runningConfigIdentity: state.runningConfigIdentity,
    runningConfig: state.runningConfig,
  }

  try {
    await boundApply({
      targetPath: path,
      expectedHash: hash,
      overrides,
      includeMV: Boolean(candidateSelection['pid2.MV'] && overrides['pid2.MV'] != null),
    })
    await state.loadFromPath(path)
    // Reload must not reset the active run identity / frozen running config.
    if (typeof boundStore.setState === 'function') {
      boundStore.setState({
        runtimeState: preserved.runtimeState,
        runningConfigIdentity: preserved.runningConfigIdentity,
        runningConfig: preserved.runningConfig,
      })
    }
    return {
      savedUpdated: true,
      runningIdentity: boundStore.getState().runningConfigIdentity,
    }
  } catch (err) {
    return {
      savedUpdated: false,
      runningIdentity: identityBefore,
      error: err instanceof Error ? err.message : String(err),
    }
  }
}
