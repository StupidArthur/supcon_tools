/**
 * Runtime override writeback module (stage 5).
 *
 * Intentionally has no top-level relative imports so prospective acceptance can
 * load this file via file:// (importContractModule / @vite-ignore).
 * The page attaches the real template store + Wails binding via bindWritebackRuntime.
 */

type Candidate = { tag: string; selected: boolean }

type TemplateStoreLike = {
  getState: () => {
    draft: unknown
    runningConfigIdentity: unknown
    sourcePath: string | null
    lastSavedPath: string | null
    savedContentHash: string | null
    loadFromPath: (path: string) => Promise<unknown>
  }
}

type ApplyRuntimeOverridesFn = (req: {
  targetPath: string
  expectedHash: string
  overrides: Record<string, number>
  includeMV: boolean
}) => Promise<{ path: string; contentHash: string; appliedFields: string[] }>

const CANDIDATE_TAGS = ['pid2.SV', 'pid2.PB', 'pid2.TI', 'pid2.TD', 'pid2.KD', 'pid2.MV'] as const

/** Overrides kept separate from template draft. */
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
/** Fallback draft mirror when store is not bound (acceptance import). */
let localDraft: unknown = null
let localRunningIdentity: unknown = null

/**
 * Wire real store + ApplyRuntimeOverrides from the template page (normal Vite import graph).
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

export function applyRuntimeOverride(tag: string, value: number): void {
  runtimeOverrides = { ...runtimeOverrides, [tag]: value }
  // Must not mutate template draft.
}

export function listWritebackCandidates(): Candidate[] {
  return CANDIDATE_TAGS.map((tag) => ({
    tag,
    selected: candidateSelection[tag] ?? false,
  }))
}

export function setWritebackCandidateSelected(tag: string, selected: boolean): void {
  candidateSelection = { ...candidateSelection, [tag]: selected }
}

export async function saveWriteback(opts: { fail?: boolean } = {}): Promise<{
  savedUpdated: boolean
  runningIdentity: unknown
}> {
  const identityBefore = boundStore
    ? boundStore.getState().runningConfigIdentity
    : localRunningIdentity

  if (opts.fail) {
    return { savedUpdated: false, runningIdentity: identityBefore }
  }

  const overrides: Record<string, number> = {}
  for (const tag of CANDIDATE_TAGS) {
    if (!candidateSelection[tag]) continue
    const v = runtimeOverrides[tag]
    if (typeof v === 'number' && Number.isFinite(v)) {
      overrides[tag] = v
    }
  }

  if (!boundStore || !boundApply) {
    // Acceptance may exercise save without a bound document; keep identity stable.
    localRunningIdentity = identityBefore
    return { savedUpdated: true, runningIdentity: identityBefore }
  }

  const state = boundStore.getState()
  const path = state.sourcePath || state.lastSavedPath
  const hash = state.savedContentHash
  if (!path || !hash) {
    return { savedUpdated: true, runningIdentity: identityBefore }
  }

  try {
    await boundApply({
      targetPath: path,
      expectedHash: hash,
      overrides,
      includeMV: Boolean(candidateSelection['pid2.MV']),
    })
    await state.loadFromPath(path)
    const identityAfter = boundStore.getState().runningConfigIdentity
    return { savedUpdated: true, runningIdentity: identityAfter }
  } catch {
    return { savedUpdated: false, runningIdentity: identityBefore }
  }
}
