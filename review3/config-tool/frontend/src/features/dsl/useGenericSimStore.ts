/**
 * Generic offline simulation state - bound to DSL project/session identity.
 *
 * 批量仿真结果本地化改造：不再在 Zustand 中保存完整 rows。
 * 只保存 batchId + 状态 + 列信息 + 预览行（最多几百行）。
 */
import { create } from 'zustand'

export type GenericSimStatus = 'idle' | 'running' | 'success' | 'failed'

export const DEFAULT_OFFLINE_SIM_CYCLES = 2000

interface GenericSimState {
  status: GenericSimStatus
  cycles: number
  completedCycles: number
  error: string | null
  /** batch 任务 ID（异步 batch 启动后由后端返回） */
  batchId: string | null
  columns: string[]
  /** 预览行（最多几百行，不包含全部 20000 行） */
  previewRows: Array<Record<string, unknown>>
  selectedColumns: string[]
  /**
   * 绘图缩放 (display_args 中的 [ref])：plotValue = raw × 100 / ref。
   */
  plotScales: Record<string, number>
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
   */
  globalBatchRunning: boolean
  globalBatchRunId: string | null
  setCycles: (n: number) => void
  setSelectedColumns: (cols: string[]) => void
  toggleColumn: (col: string) => void
  beginGlobalBatch: (runId: string) => void
  endGlobalBatch: (runId: string) => void
  beginRun: (opts: { projectId: string; yamlHash: string; cycles: number; epoch: number }) => string
  /** batch 启动成功后保存 batchId */
  setBatchId: (batchId: string) => void
  /** 轮询状态更新 */
  pollStatus: (payload: {
    completedCycles: number
    cyclesRequested: number
  }) => void
  succeed: (payload: {
    projectId: string
    runId: string
    epoch: number
    columns: string[]
    previewRows: Array<Record<string, unknown>>
    completedCycles: number
    currentYamlHash: string
    displayColumns?: string[]
    plotScales?: Record<string, number>
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
  batchId: null,
  columns: [],
  previewRows: [],
  selectedColumns: [],
  plotScales: {},
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
      batchId: null,
      columns: [],
      previewRows: [],
      selectedColumns: [],
      plotScales: {},
      boundProjectId: projectId,
      boundRunId: runId,
      boundYamlHash: yamlHash,
      stale: false,
      epoch,
    })
    return runId
  },

  setBatchId: (batchId) => set({ batchId }),

  pollStatus: ({ completedCycles, cyclesRequested }) => {
    const s = get()
    if (s.status !== 'running') return
    set({ completedCycles })
  },

  succeed: ({ projectId, runId, epoch, columns, previewRows, completedCycles, currentYamlHash, displayColumns, plotScales }) => {
    const s = get()
    if (s.epoch !== epoch || s.boundProjectId !== projectId || s.boundRunId !== runId) {
      return false
    }
    const stale = currentYamlHash !== s.boundYamlHash
    const columnSet = new Set(columns)
    let selectedColumns = (displayColumns ?? []).filter((c) => columnSet.has(c))
    // 兜底：displayColumns 为空或无效时，自动选前 1~8 个数值业务列
    if (selectedColumns.length === 0 && previewRows.length > 0) {
      const businessCols = columns.filter(
        (c) => !c.startsWith('_') && c !== '_cycle' && c !== '_sim_time' && c !== '_need_sample',
      )
      selectedColumns = businessCols.slice(0, 8).filter((c) => {
        for (const row of previewRows.slice(0, 50)) {
          const v = row[c]
          if (typeof v === 'number' && Number.isFinite(v)) return true
        }
        return false
      })
    }
    const plotScalesFiltered: Record<string, number> = {}
    if (plotScales) {
      for (const c of columns) {
        const v = plotScales[c]
        if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
          plotScalesFiltered[c] = v
        }
      }
    }
    set({
      status: 'success',
      columns,
      previewRows,
      completedCycles,
      error: null,
      selectedColumns,
      plotScales: plotScalesFiltered,
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
    if (s.status === 'running' || (s.status === 'success' && s.previewRows.length > 0)) {
      set({ stale: true })
    }
  },

  clearResults: () =>
    set((s) => ({
      status: 'idle',
      error: null,
      batchId: null,
      columns: [],
      previewRows: [],
      selectedColumns: [],
      plotScales: {},
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
      s.previewRows.length > 0
    )
  },

  hasDisplayResult: (projectId) => {
    const s = get()
    return s.boundProjectId === projectId && s.previewRows.length > 0 && s.status === 'success'
  },
}))
