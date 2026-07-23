import { create } from 'zustand'
import { realtimeProjectApi } from '../../lib/api'
import type {
  DuplicateInstance,
  ExpandedInstance,
  ProjectSummary,
  RealtimeProject,
} from './types'

interface RealtimeProjectState {
  projects: ProjectSummary[]
  currentProject: RealtimeProject | null
  instances: ExpandedInstance[]
  duplicates: DuplicateInstance[]
  loading: boolean
  error: string | null

  refreshProjects: () => Promise<void>
  createProject: (name: string) => Promise<void>
  openProject: (id: string) => Promise<void>
  deleteProject: (id: string) => Promise<void>
  addSource: (projectId: string) => Promise<void>
  removeSource: (projectId: string, sourceId: string) => Promise<void>
  updateReplicas: (projectId: string, sourceId: string, replicas: number) => Promise<boolean>
  clearError: () => void
}

export const useRealtimeProjectStore = create<RealtimeProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  instances: [],
  duplicates: [],
  loading: false,
  error: null,

  refreshProjects: async () => {
    try {
      const projects = await realtimeProjectApi.listProjects()
      set({ projects })
    } catch (e: any) {
      set({ error: String(e) })
    }
  },

  createProject: async (name: string) => {
    set({ loading: true, error: null })
    try {
      const project = await realtimeProjectApi.createProject(name)
      set({
        currentProject: project as any,
        instances: [],
        duplicates: [],
        loading: false,
      })
      await get().refreshProjects()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  openProject: async (id: string) => {
    set({ loading: true, error: null })
    try {
      const project = await realtimeProjectApi.openProject(id)
      const validation = await realtimeProjectApi.validateProject(id)
      set({
        currentProject: project as any,
        instances: (validation as any).instances || [],
        duplicates: (validation as any).duplicates || [],
        loading: false,
      })
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  deleteProject: async (id: string) => {
    set({ loading: true, error: null })
    try {
      await realtimeProjectApi.deleteProject(id)
      const { currentProject } = get()
      if (currentProject?.id === id) {
        set({ currentProject: null, instances: [], duplicates: [] })
      }
      set({ loading: false })
      await get().refreshProjects()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  addSource: async (projectId: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const view = await realtimeProjectApi.addSource(projectId)
      if (!view || !view.project) {
        set({ loading: false })
        return
      }
      set({
        currentProject: view.project as any,
        instances: (view.validation as any)?.instances || [],
        duplicates: [],
        loading: false,
      })
      await get().refreshProjects()
    } catch (e: any) {
      const msg = String(e)
      if (msg.includes('DUPLICATE_INSTANCE_NAMES') || msg.includes('实例名称重复')) {
        try {
          const validation = await realtimeProjectApi.validateProject(projectId)
          set({ duplicates: (validation as any).duplicates || [], loading: false })
        } catch {
          set({ error: msg, loading: false })
        }
      } else {
        set({ error: msg, loading: false })
      }
    }
  },

  removeSource: async (projectId: string, sourceId: string) => {
    set({ loading: true, error: null })
    try {
      const view = await realtimeProjectApi.removeSource(projectId, sourceId)
      set({
        currentProject: view.project as any,
        instances: (view.validation as any)?.instances || [],
        duplicates: [],
        loading: false,
      })
      await get().refreshProjects()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  updateReplicas: async (projectId: string, sourceId: string, replicas: number) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const view = await realtimeProjectApi.updateReplicas(projectId, sourceId, replicas)
      set({
        currentProject: view.project as any,
        instances: (view.validation as any)?.instances || [],
        duplicates: [],
        loading: false,
      })
      return true
    } catch (e: any) {
      const msg = String(e)
      if (msg.includes('DUPLICATE_INSTANCE_NAMES') || msg.includes('实例名称重复')) {
        try {
          const validation = await realtimeProjectApi.validateProject(projectId)
          set({ duplicates: (validation as any).duplicates || [], loading: false })
        } catch {
          set({ error: msg, loading: false })
        }
      } else {
        set({ error: msg, loading: false })
      }
      return false
    }
  },

  clearError: () => set({ error: null, duplicates: [] }),
}))
