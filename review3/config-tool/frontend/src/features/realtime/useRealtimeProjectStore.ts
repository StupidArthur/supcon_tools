import { create } from 'zustand'
import { realtimeProjectApi } from '../../lib/api'
import type {
  DuplicateInstance,
  ExpandedInstance,
  ProjectView,
  RealtimeRuntime,
} from './types'

interface RealtimeProjectState {
  /** 当前工程（来自 project.yaml，不含绝对路径） */
  currentProject: ProjectView | null
  /** 当前 project.yaml 的绝对路径（仅内存，不写入工程文件） */
  currentProjectFile: string | null
  instances: ExpandedInstance[]
  duplicates: DuplicateInstance[]
  loading: boolean
  error: string | null

  openExistingProject: () => Promise<void>
  createProjectAt: (name: string, parentDir: string) => Promise<void>
  addSource: (projectId: string, projectFile: string) => Promise<void>
  removeSource: (projectId: string, projectFile: string, sourceId: string) => Promise<void>
  updateReplicas: (projectId: string, projectFile: string, sourceId: string, replicas: number) => Promise<boolean>
  updateRuntime: (projectId: string, projectFile: string, rt: RealtimeRuntime) => Promise<void>
  clearError: () => void
}

export const useRealtimeProjectStore = create<RealtimeProjectState>((set, get) => ({
  currentProject: null,
  currentProjectFile: null,
  instances: [],
  duplicates: [],
  loading: false,
  error: null,

  openExistingProject: async () => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const path = await realtimeProjectApi.chooseProjectFile()
      if (!path) {
        set({ loading: false })
        return
      }
      const view = await realtimeProjectApi.openProjectFile(path)
      // view 是 OpenedProject，包含 projectFile
      const proj = view as unknown as ProjectView
      // 不重新走 addSource 校验；openProjectFile 内部已完成编译校验。
      // instances/duplicates 由 validate API 显式拉取。
      const validation = await realtimeProjectApi.validateProject(proj.id).catch(() => null)
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || path,
        instances: (validation as any)?.instances || [],
        duplicates: (validation as any)?.duplicates || [],
        loading: false,
      })
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  createProjectAt: async (name: string, parentDir: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const proj = (await realtimeProjectApi.createProjectAt(name, parentDir)) as unknown as ProjectView
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || null,
        instances: [],
        duplicates: [],
        loading: false,
      })
      void get()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  addSource: async (projectId: string, projectFile: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const yamlPath = await realtimeProjectApi.chooseSourceYAML()
      if (!yamlPath) {
        set({ loading: false })
        return
      }
      const view = (await realtimeProjectApi.addSourceAt(projectId, projectFile, yamlPath)) as any
      if (!view || !view.project) {
        set({ loading: false })
        return
      }
      if (view.applied === false) {
        set({
          duplicates: view.validation?.duplicates || [],
          loading: false,
        })
        return
      }
      set({
        currentProject: { ...view.project, projectFile: view.project.projectFile || projectFile },
        currentProjectFile: view.project.projectFile || projectFile,
        instances: view.validation?.instances || [],
        duplicates: [],
        loading: false,
      })
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  removeSource: async (projectId: string, projectFile: string, sourceId: string) => {
    set({ loading: true, error: null })
    try {
      const view = (await realtimeProjectApi.removeSourceAt(projectId, projectFile, sourceId)) as any
      set({
        currentProject: { ...view.project, projectFile: view.project.projectFile || projectFile },
        currentProjectFile: view.project.projectFile || projectFile,
        instances: view.validation?.instances || [],
        duplicates: [],
        loading: false,
      })
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  updateReplicas: async (projectId, projectFile, sourceId, replicas) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const view = (await realtimeProjectApi.updateReplicasAt(projectId, projectFile, sourceId, replicas)) as any
      if (view.applied === false) {
        set({
          duplicates: view.validation?.duplicates || [],
          loading: false,
        })
        return false
      }
      set({
        currentProject: { ...view.project, projectFile: view.project.projectFile || projectFile },
        currentProjectFile: view.project.projectFile || projectFile,
        instances: view.validation?.instances || [],
        duplicates: [],
        loading: false,
      })
      return true
    } catch (e: any) {
      set({ error: String(e), loading: false })
      return false
    }
  },

  updateRuntime: async (projectId, projectFile, rt) => {
    try {
      const proj = (await realtimeProjectApi.updateRuntime(projectId, projectFile, rt)) as unknown as ProjectView
      set({
        currentProject: { ...proj, projectFile: proj.projectFile || projectFile },
        currentProjectFile: proj.projectFile || projectFile,
      })
    } catch (e: any) {
      set({ error: String(e) })
    }
  },

  clearError: () => set({ error: null, duplicates: [] }),
}))