/**
 * Generic offline simulation state — bound to DSL project/session identity.
 */
import { create } from 'zustand'

export type GenericSimStatus = 'idle' | 'running' | 'success' | 'failed'

export const DEFAULT_OFFLINE_SIM_CYCLES = 2000

interface GenericSimState {
  status: GenericSimStatus
  cycles: number
  completedCycles: number
  error: string | null
  columns: string[]
  rows: Array<Record<string, unknown>>
  selectedColumns: string[]
  lastTempPath: string | null
  /** Project/session that owns the current (or in-flight) result. */
  boundProjectId: string | null
  /** Run id of in-flight or last completed run. */
  boundRunId: string | null
  /** YAML hash captured at beginRun. */
  boundYamlHash: string | null
  /** True when YAML edited after a successful run for this project. */
  stale: boolean
  /** Invalidates in-flight runs (incremented on project switch / clear). */
  epoch: number
  setCycles: (n: number) => void
  setSelectedColumns: (cols: string[]) => void
  toggleColumn: (col: string) => void
  beginRun: (opts: { projectId: string; yamlHash: string; cycles: number; epoch: number }) => string
  succeed: (payload: {
    projectId: string
    runId: string
    epoch: number
    columns: string[]
    rows: Array<Record<string, unknown>>
    completedCycles: number
    /** Hash of current project yamlText at completion time (compared to boundYamlHash). */
    currentYamlHash: string
  }) => boolean
  fail: (payload: { projectId: string; runId: string; epoch: number; error: string }) => boolean
  markStale: () => void
  clearResults: () => void
  bumpEpoch: () => number
  isRunning: () => boolean
  hasExportableResult: (projectId: string) => boolean
  hasDisplayResult: (projectId: string) => boolean
}

function pickDefaultColumns(columns: string[]): string[] {
  const numericHints = columns.filter((c) => c !== '_cycle')
  return numericHints.slice(0, Math.min(3, numericHints.length))
}

function newRunId(): string {
  return `r_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

export function hashYamlText(text: string): string {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return `y${(h >>> 0).toString(16)}_${text.length}`
}

export const useGenericSimStore = create<GenericSimState>((set, get) => ({
  status: 'idle',
  cycles: DEFAULT_OFFLINE_SIM_CYCLES,
  completedCycles: 0,
  error: null,
  columns: [],
  rows: [],
  selectedColumns: [],
  lastTempPath: null,
  boundProjectId: null,
  boundRunId: null,
  boundYamlHash: null,
  stale: false,
  epoch: 0,

  setCycles: (cycles) => set({ cycles: Math.max(1, Math.floor(cycles) || DEFAULT_OFFLINE_SIM_CYCLES) }),
  setSelectedColumns: (selectedColumns) => set({ selectedColumns }),
  toggleColumn: (col) => {
    const cur = get().selectedColumns
    set({
      selectedColumns: cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col],
    })
  },

  beginRun: ({ projectId, yamlHash, cycles, epoch }) => {
    const runId = newRunId()
    set({
      status: 'running',
      cycles,
      completedCycles: 0,
      error: null,
      columns: [],
      rows: [],
      selectedColumns: [],
      boundProjectId: projectId,
      boundRunId: runId,
      boundYamlHash: yamlHash,
      stale: false,
      epoch,
    })
    return runId
  },

  succeed: ({ projectId, runId, epoch, columns, rows, completedCycles, currentYamlHash }) => {
    const s = get()
    if (s.epoch !== epoch || s.boundProjectId !== projectId || s.boundRunId !== runId) {
      return false
    }
    // Completion hash compare is authoritative (not unconditional stale=false).
    const stale = currentYamlHash !== s.boundYamlHash
    set({
      status: 'success',
      columns,
      rows,
      completedCycles,
      error: null,
      selectedColumns: pickDefaultColumns(columns),
      stale,
    })
    return true
  },

  fail: ({ projectId, runId, epoch, error }) => {
    const s = get()
    if (s.epoch !== epoch || s.boundProjectId !== projectId || s.boundRunId !== runId) {
      return false
    }
    set({
      status: 'failed',
      error,
      completedCycles: 0,
    })
    return true
  },

  markStale: () => {
    const s = get()
    // Running: record that this run is already outdated when it finishes.
    // Success: mark display/export as expired after post-run edits.
    if (s.status === 'running' || (s.status === 'success' && s.rows.length > 0)) {
      set({ stale: true })
    }
  },

  clearResults: () =>
    set((s) => ({
      status: 'idle',
      error: null,
      columns: [],
      rows: [],
      selectedColumns: [],
      completedCycles: 0,
      lastTempPath: null,
      boundProjectId: null,
      boundRunId: null,
      boundYamlHash: null,
      stale: false,
      epoch: s.epoch + 1,
    })),

  bumpEpoch: () => {
    const next = get().epoch + 1
    set({ epoch: next })
    return next
  },

  isRunning: () => get().status === 'running',

  hasExportableResult: (projectId) => {
    const s = get()
    return (
      s.status === 'success' &&
      !s.stale &&
      s.boundProjectId === projectId &&
      s.rows.length > 0
    )
  },

  hasDisplayResult: (projectId) => {
    const s = get()
    return s.boundProjectId === projectId && s.rows.length > 0 && s.status === 'success'
  },
}))
