import { create } from 'zustand'
import type { YAMLConfig, BatchResult, EngineStatus, LogEntry, RunMode } from '../types'
import { debugApi } from '../lib/api'

interface Store {
  // --- 路径与配置 ---
  workDir: string         // review3 目录（含 standalone_main.py）
  pythonPath: string      // python.exe 路径（空则从 PATH 查找）
  configPath: string
  configs: string[]
  yamlConfig: YAMLConfig | null

  // --- 运行参数 ---
  runMode: RunMode
  cycles: number
  cycleTime: number
  opcPort: number
  clockMode: string

  // --- 运行状态 ---
  engineStatus: EngineStatus | null
  running: boolean
  batchRunning: boolean

  // --- 数据 ---
  batchResult: BatchResult | null
  logs: LogEntry[]

  // --- Actions ---
  setWorkDir: (dir: string) => void
  setPythonPath: (path: string) => void
  setConfigPath: (path: string) => void
  setRunMode: (mode: RunMode) => void
  setCycles: (n: number) => void
  setCycleTime: (t: number) => void
  setOpcPort: (p: number) => void
  setClockMode: (m: string) => void

  refreshConfigs: () => Promise<void>
  loadYAMLConfig: (path: string) => Promise<void>

  addLog: (source: string, text: string) => void
  clearLogs: () => void

  setEngineStatus: (s: EngineStatus | null) => void
  setBatchResult: (r: BatchResult | null) => void
  setRunning: (r: boolean) => void
  setBatchRunning: (r: boolean) => void
}

const MAX_LOGS = 500

export const useStore = create<Store>((set, get) => ({
  workDir: '',
  pythonPath: '',
  configPath: '',
  configs: [],
  yamlConfig: null,

  runMode: 'batch',
  cycles: 1000,
  cycleTime: 0.5,
  opcPort: 18951,
  clockMode: 'REALTIME',

  engineStatus: null,
  running: false,
  batchRunning: false,

  batchResult: null,
  logs: [],

  setWorkDir: (dir) => set({ workDir: dir }),
  setPythonPath: (path) => set({ pythonPath: path }),
  setConfigPath: (path) => set({ configPath: path }),
  setRunMode: (mode) => set({ runMode: mode }),
  setCycles: (n) => set({ cycles: n }),
  setCycleTime: (t) => set({ cycleTime: t }),
  setOpcPort: (p) => set({ opcPort: p }),
  setClockMode: (m) => set({ clockMode: m }),

  refreshConfigs: async () => {
    const { workDir } = get()
    if (!workDir) return
    try {
      const configs = await debugApi.listConfigs(workDir)
      set({ configs })
    } catch (e) {
      console.error('refreshConfigs error:', e)
    }
  },

  loadYAMLConfig: async (path) => {
    try {
      const cfg = await debugApi.parseYAMLConfig(path)
      set({
        yamlConfig: cfg,
        cycleTime: cfg.clock.cycleTime || 0.5,
        clockMode: cfg.clock.mode || 'REALTIME',
      })
    } catch (e) {
      console.error('loadYAMLConfig error:', e)
    }
  },

  addLog: (source, text) =>
    set((state) => ({
      logs: [...state.logs.slice(-MAX_LOGS + 1), { ts: Date.now(), source, text }],
    })),

  clearLogs: () => set({ logs: [] }),

  setEngineStatus: (s) => set({ engineStatus: s }),
  setBatchResult: (r) => set({ batchResult: r }),
  setRunning: (r) => set({ running: r }),
  setBatchRunning: (r) => set({ batchRunning: r }),
}))
