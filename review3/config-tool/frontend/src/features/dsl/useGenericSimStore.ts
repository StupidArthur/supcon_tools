/**
 * Generic offline simulation state — independent of second-order tank template store.
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
  setCycles: (n: number) => void
  setSelectedColumns: (cols: string[]) => void
  toggleColumn: (col: string) => void
  beginRun: (cycles: number) => void
  succeed: (payload: {
    columns: string[]
    rows: Array<Record<string, unknown>>
    completedCycles: number
  }) => void
  fail: (error: string) => void
  clearResults: () => void
  isRunning: () => boolean
  hasResult: () => boolean
}

function pickDefaultColumns(columns: string[]): string[] {
  const numericHints = columns.filter((c) => c !== '_cycle')
  return numericHints.slice(0, Math.min(3, numericHints.length))
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

  setCycles: (cycles) => set({ cycles: Math.max(1, Math.floor(cycles) || DEFAULT_OFFLINE_SIM_CYCLES) }),
  setSelectedColumns: (selectedColumns) => set({ selectedColumns }),
  toggleColumn: (col) => {
    const cur = get().selectedColumns
    set({
      selectedColumns: cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col],
    })
  },

  beginRun: (cycles) =>
    set({
      status: 'running',
      cycles,
      completedCycles: 0,
      error: null,
      // Keep previous results visible until success replaces them? Spec: new run replaces.
      columns: [],
      rows: [],
      selectedColumns: [],
    }),

  succeed: ({ columns, rows, completedCycles }) =>
    set({
      status: 'success',
      columns,
      rows,
      completedCycles,
      error: null,
      selectedColumns: pickDefaultColumns(columns),
    }),

  fail: (error) =>
    set({
      status: 'failed',
      error,
      completedCycles: 0,
    }),

  clearResults: () =>
    set({
      status: 'idle',
      error: null,
      columns: [],
      rows: [],
      selectedColumns: [],
      completedCycles: 0,
      lastTempPath: null,
    }),

  isRunning: () => get().status === 'running',
  hasResult: () => get().status === 'success' && get().rows.length > 0,
}))
