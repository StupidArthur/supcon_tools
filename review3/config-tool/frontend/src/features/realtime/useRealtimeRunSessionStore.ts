import { create } from 'zustand'
import { realtimeRuntimeApi } from '../../lib/api'

export interface RealtimeRunSession {
  sessionId: string
  sourceKind: 'project' | 'single-yaml'
  projectId?: string
  projectName?: string
  sourcePath?: string
  runtimeRevision: string
  compiledConfigPath: string
  configHash: string
  runtimeName: string
  cycleTime: number
  opcUaPort: number
  apiHost: string
  apiPort: number
  startedAt: string
  state: string
}

export interface RealtimeStartOptions {
  cycleTime: number
  opcUaPort: number
  apiHost: string
  apiPort: number
  runtimeName: string
}

interface RealtimeRunSessionState {
  session: RealtimeRunSession | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  startProject: (projectId: string, options: RealtimeStartOptions) => Promise<boolean>
  startSingleYaml: (configPath: string, options: RealtimeStartOptions) => Promise<boolean>
  stop: () => Promise<void>
  clearError: () => void
}

export const useRealtimeRunSessionStore = create<RealtimeRunSessionState>((set) => ({
  session: null,
  loading: false,
  error: null,

  refresh: async () => {
    try {
      const s = await realtimeRuntimeApi.getSession()
      set({ session: (s as any) || null })
    } catch {
      // ignore
    }
  },

  startProject: async (projectId, options) => {
    set({ loading: true, error: null })
    try {
      const s = await realtimeRuntimeApi.startProject(projectId, options as any)
      set({ session: s as any, loading: false })
      return true
    } catch (e: any) {
      set({ error: String(e), loading: false })
      return false
    }
  },

  startSingleYaml: async (configPath, options) => {
    set({ loading: true, error: null })
    try {
      const s = await realtimeRuntimeApi.startSingleYAML(configPath, options as any)
      set({ session: s as any, loading: false })
      return true
    } catch (e: any) {
      set({ error: String(e), loading: false })
      return false
    }
  },

  stop: async () => {
    set({ loading: true, error: null })
    try {
      await realtimeRuntimeApi.stop()
      set({ session: null, loading: false })
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  clearError: () => set({ error: null }),
}))
