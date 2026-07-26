import { create } from 'zustand'
import { realtimeProjectApi, type RecentProjectEntry } from '../../lib/api'
import type {
  DuplicateInstance,
  ExpandedInstance,
  ProjectView,
  RealtimeRuntime,
} from './types'

/**
 * 把 Wails 返回的 OpenedProject（嵌套结构 {project, projectFile, projectDir}）
 * 扁平化为 ProjectView（{sources, runtime, projectFile, projectDir}）。
 * 后端 CreateProjectAt / OpenProjectFile 都返回嵌套结构；前端 ProjectView 期望扁平。
 * 扁平化必须 sources / runtime 都来自内层 project，避免渲染时出现 undefined.sources。
 */
function flattenOpenedProject(opened: unknown): ProjectView {
  const o = opened as { project?: any; projectFile?: string; projectDir?: string }
  const p = o?.project || {}
  return {
    version: p.version,
    id: p.id,
    name: p.name,
    sources: Array.isArray(p.sources) ? p.sources : [],
    runtime: p.runtime,
    projectFile: o?.projectFile,
    projectDir: o?.projectDir,
  } as ProjectView
}

interface RealtimeProjectState {
  /** 当前工程（来自 project.yaml，不含绝对路径） */
  currentProject: ProjectView | null
  /** 当前 project.yaml 的绝对路径（仅内存，不写入工程文件） */
  currentProjectFile: string | null
  instances: ExpandedInstance[]
  duplicates: DuplicateInstance[]
  loading: boolean
  error: string | null
  /** 最近打开工程（持久化到 <exe>/recent_projects.json） */
  recentProjects: RecentProjectEntry[]

  openExistingProject: () => Promise<void>
  /** 新建工程：自动创建到 <exe>/project/<工程名>/，不弹出目录选择器。 */
  createProject: (name: string) => Promise<void>
  /** 保留显式 parentDir 入口，供测试 / 高级用户使用。 */
  createProjectAt: (name: string, parentDir: string) => Promise<void>
  addSource: (projectId: string, projectFile: string) => Promise<void>
  removeSource: (projectId: string, projectFile: string, sourceId: string) => Promise<void>
  updateReplicas: (projectId: string, projectFile: string, sourceId: string, replicas: number) => Promise<boolean>
  updateRuntime: (projectId: string, projectFile: string, rt: RealtimeRuntime) => Promise<void>
  refreshRecentProjects: () => Promise<void>
  openRecentProject: (projectFile: string) => Promise<void>
  clearError: () => void
}

type FetchValidationResult =
  | { ok: true; instances: ExpandedInstance[]; duplicates: DuplicateInstance[] }
  | { ok: false; error: string }

async function fetchValidation(projectId: string): Promise<FetchValidationResult> {
  try {
    const validation = (await realtimeProjectApi.validateProject(projectId)) as any
    return {
      ok: true,
      instances: validation?.instances || [],
      duplicates: validation?.duplicates || [],
    }
  } catch (e: any) {
    const msg =
      typeof e === 'string'
        ? e
        : e?.message || String(e) || '校验工程失败'
    return { ok: false, error: `工程校验失败：${msg}` }
  }
}

async function rememberRecent(projectFile: string): Promise<void> {
  try {
    await realtimeProjectApi.addRecentProject(projectFile)
  } catch {
    // 单条失败不应阻断主流程
  }
}

export const useRealtimeProjectStore = create<RealtimeProjectState>((set, get) => ({
  currentProject: null,
  currentProjectFile: null,
  instances: [],
  duplicates: [],
  loading: false,
  error: null,
  recentProjects: [],

  refreshRecentProjects: async () => {
    try {
      const list = await realtimeProjectApi.listRecentProjects()
      set({ recentProjects: list })
    } catch {
      set({ recentProjects: [] })
    }
  },

  openExistingProject: async () => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const path = await realtimeProjectApi.chooseProjectFile()
      if (!path) {
        set({ loading: false })
        return
      }
      await get().openRecentProject(path)
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  openRecentProject: async (projectFile: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const opened = await realtimeProjectApi.openProjectFile(projectFile)
      const proj = flattenOpenedProject(opened)
      const validation = await fetchValidation(proj.id)
      // 记录到最近列表
      void rememberRecent(proj.projectFile || projectFile)
      if (!validation.ok) {
        // 校验失败必须显式传递给前端，不得把请求错误转换为空实例。
        set({
          currentProject: proj,
          currentProjectFile: proj.projectFile || projectFile,
          instances: [],
          duplicates: [],
          error: validation.error,
          loading: false,
        })
        void get().refreshRecentProjects()
        return
      }
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || projectFile,
        instances: validation.instances,
        duplicates: validation.duplicates,
        loading: false,
      })
      // 刷新最近列表，使已打开的项前移
      void get().refreshRecentProjects()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  createProject: async (name: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const opened = await realtimeProjectApi.createProject(name)
      const proj = flattenOpenedProject(opened)
      void rememberRecent(proj.projectFile || '')
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || null,
        instances: [],
        duplicates: [],
        loading: false,
      })
      void get().refreshRecentProjects()
    } catch (e: any) {
      set({ error: String(e), loading: false })
    }
  },

  createProjectAt: async (name: string, parentDir: string) => {
    set({ loading: true, error: null, duplicates: [] })
    try {
      const opened = await realtimeProjectApi.createProjectAt(name, parentDir)
      const proj = flattenOpenedProject(opened)
      void rememberRecent(proj.projectFile || '')
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || null,
        instances: [],
        duplicates: [],
        loading: false,
      })
      void get().refreshRecentProjects()
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
      // 后端返回 OpenedProjectView：{ applied, project: OpenedProject, validation }
      // OpenedProject 仍是嵌套 { project: Project, projectFile, projectDir }
      // 必须 flattenOpenedProject 才能让 currentProject.sources / runtime 可访问
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
      const proj = flattenOpenedProject(view.project)
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || projectFile,
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
      const proj = flattenOpenedProject(view.project)
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || projectFile,
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
      const proj = flattenOpenedProject(view.project)
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || projectFile,
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
      const opened = await realtimeProjectApi.updateRuntime(projectId, projectFile, rt)
      const proj = flattenOpenedProject(opened)
      set({
        currentProject: proj,
        currentProjectFile: proj.projectFile || projectFile,
      })
    } catch (e: any) {
      set({ error: String(e) })
    }
  },

  clearError: () => set({ error: null, duplicates: [] }),
}))