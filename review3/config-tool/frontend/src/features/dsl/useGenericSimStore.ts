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
  /**
   * 全局 DataFactory 批量任务占用状态（与「当前工程结果状态」分离）。
   * 工程切换 / 返回首页 / 清空结果都不会清除；只有发起任务在自己 finally 里、
   * 且 runId 仍匹配时才释放（lease 语义），避免旧任务清掉后来任务的状态。
   */
  globalBatchRunning: boolean
  globalBatchRunId: string | null
  setCycles: (n: number) => void
  setSelectedColumns: (cols: string[]) => void
  toggleColumn: (col: string) => void
  beginGlobalBatch: (runId: string) => void
  endGlobalBatch: (runId: string) => void
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
    /** DSL display_args 声明的默认绘图列（来自引擎），作为默认选中；YAML 未声明时为空。 */
    displayColumns?: string[]
  }) => boolean
  fail: (payload: { projectId: string; runId: string; epoch: number; error: string }) => boolean
  markStale: () => void
  clearResults: () => void
  bumpEpoch: () => number
  isRunning: () => boolean
  hasExportableResult: (projectId: string) => boolean
  hasDisplayResult: (projectId: string) => boolean
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
  boundProjectId: null,
  boundRunId: null,
  boundYamlHash: null,
  stale: false,
  epoch: 0,
  globalBatchRunning: false,
  globalBatchRunId: null,

  setCycles: (cycles) => set({ cycles: Math.max(1, Math.floor(cycles) || DEFAULT_OFFLINE_SIM_CYCLES) }),
  setSelectedColumns: (selectedColumns) => set({ selectedColumns }),
  toggleColumn: (col) => {
    const cur = get().selectedColumns
    set({
      selectedColumns: cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col],
    })
  },

  beginGlobalBatch: (runId) => set({ globalBatchRunning: true, globalBatchRunId: runId }),
  endGlobalBatch: (runId) => {
    // lease 语义：只释放自己发起的任务，不能清掉后来任务的状态。
    if (get().globalBatchRunId === runId) {
      set({ globalBatchRunning: false, globalBatchRunId: null })
    }
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

  succeed: ({ projectId, runId, epoch, columns, rows, completedCycles, currentYamlHash, displayColumns }) => {
    const s = get()
    if (s.epoch !== epoch || s.boundProjectId !== projectId || s.boundRunId !== runId) {
      return false
    }
    // Completion hash compare is authoritative (not unconditional stale=false).
    const stale = currentYamlHash !== s.boundYamlHash
    // 默认绘图列完全由 YAML 的 display_args 驱动（引擎 get_display_variables）；
    // 仅保留 CSV 实际存在的列，YAML 未声明则为空（由用户手动勾选）。
    const columnSet = new Set(columns)
    const selectedColumns = (displayColumns ?? []).filter((c) => columnSet.has(c))
    set({
      status: 'success',
      columns,
      rows,
      completedCycles,
      error: null,
      selectedColumns,
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
