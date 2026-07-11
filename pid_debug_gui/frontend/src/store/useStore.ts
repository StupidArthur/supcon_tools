import { create } from 'zustand'
import type { ConnectionState, StatusResponse, MetaResponse, DisplayVar } from '../types'

interface AppState {
  connectionState: ConnectionState
  baseUrl: string
  instanceName: string
  status: StatusResponse | null
  meta: MetaResponse | null
  displayVars: DisplayVar[]
  snapshotHistory: Record<string, number | boolean>[]
  selectedVars: string[]
  safeState: boolean

  setConnectionState: (s: ConnectionState) => void
  setBaseUrl: (url: string) => void
  setInstanceName: (name: string) => void
  setStatus: (s: StatusResponse | null) => void
  setMeta: (m: MetaResponse | null) => void
  setDisplayVars: (v: DisplayVar[]) => void
  pushSnapshot: (snap: Record<string, number | boolean>) => void
  setSelectedVars: (v: string[]) => void
  setSafeState: (v: boolean) => void
  reset: () => void
}

const MAX_HISTORY = 2000

export const useStore = create<AppState>((set) => ({
  connectionState: 'disconnected',
  baseUrl: 'http://127.0.0.1:8000',
  instanceName: '',
  status: null,
  meta: null,
  displayVars: [],
  snapshotHistory: [],
  selectedVars: [],
  safeState: false,

  setConnectionState: (s) => set({ connectionState: s }),
  setBaseUrl: (url) => set({ baseUrl: url }),
  setInstanceName: (name) => set({ instanceName: name }),
  setStatus: (s) => set({ status: s }),
  setMeta: (m) => set({ meta: m }),
  setDisplayVars: (v) => set({ displayVars: v }),

  pushSnapshot: (snap) =>
    set((state) => {
      const history = [...state.snapshotHistory, snap]
      if (history.length > MAX_HISTORY) {
        history.splice(0, Math.floor(MAX_HISTORY / 4))
      }
      return { snapshotHistory: history }
    }),

  setSelectedVars: (v) => set({ selectedVars: v }),
  setSafeState: (v) => set({ safeState: v }),

  reset: () =>
    set({
      connectionState: 'disconnected',
      instanceName: '',
      status: null,
      meta: null,
      displayVars: [],
      snapshotHistory: [],
      selectedVars: [],
      safeState: false,
    }),
}))
