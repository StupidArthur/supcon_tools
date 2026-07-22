/**
 * Lightweight DSL project UI store (presentation / navigation only).
 */
import { create } from 'zustand'
import type { DslEditorTab, DslPhase, DslSimTab } from '../app/navigation'
import { useGenericSimStore } from './useGenericSimStore'

export type DslProjectKind = 'none' | 'template' | 'generic'

interface DslProjectState {
  /** Unique id for the current open/new/switch session. */
  projectId: string
  phase: DslPhase
  editorTab: DslEditorTab
  simTab: DslSimTab
  projectKind: DslProjectKind
  /** Display name / basename for workspace header. */
  projectName: string
  /** Currently opened file path (may be empty for unsaved draft). */
  filePath: string
  /** Raw YAML buffer for the YAML editor tab. */
  yamlText: string
  yamlDirty: boolean
  yamlError: string | null
  recentPaths: string[]
  /** Last temp YAML used for draft simulation (informational). */
  lastDraftSimPath: string | null
  setPhase: (p: DslPhase) => void
  setEditorTab: (t: DslEditorTab) => void
  setSimTab: (t: DslSimTab) => void
  setYamlText: (text: string, dirty?: boolean) => void
  setYamlError: (err: string | null) => void
  setLastDraftSimPath: (path: string | null) => void
  pushRecent: (path: string) => void
  /** Update saved path without rotating project/session (e.g. after Save As). */
  setProjectFile: (filePath: string, projectName?: string) => void
  openHome: () => void
  openWorkspace: (opts?: {
    editorTab?: DslEditorTab
    simTab?: DslSimTab
    projectKind?: DslProjectKind
    projectName?: string
    filePath?: string
  }) => void
}

const RECENT_KEY = 'review3.dsl.recentPaths'
const MAX_RECENT = 8

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

function saveRecent(paths: string[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(paths.slice(0, MAX_RECENT)))
  } catch {
    // ignore
  }
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

export function newProjectId(): string {
  return `p_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`
}

function clearSimForProjectSwitch() {
  useGenericSimStore.getState().clearResults()
}

export const useDslProjectStore = create<DslProjectState>((set, get) => ({
  projectId: newProjectId(),
  phase: 'home',
  editorTab: 'yaml',
  simTab: 'run',
  projectKind: 'none',
  projectName: '',
  filePath: '',
  yamlText: '',
  yamlDirty: false,
  yamlError: null,
  recentPaths: loadRecent(),
  lastDraftSimPath: null,

  setPhase: (phase) => set({ phase }),
  setEditorTab: (editorTab) => set({ editorTab }),
  setSimTab: (simTab) => set({ simTab }),
  setYamlText: (yamlText, dirty = true) => {
    set({ yamlText, yamlDirty: dirty, yamlError: null })
    if (dirty) {
      useGenericSimStore.getState().markStale()
    }
  },
  setYamlError: (yamlError) => set({ yamlError }),
  setLastDraftSimPath: (lastDraftSimPath) => set({ lastDraftSimPath }),

  pushRecent: (path) => {
    if (!path) return
    const next = [path, ...get().recentPaths.filter((p) => p !== path)].slice(0, MAX_RECENT)
    saveRecent(next)
    set({ recentPaths: next })
  },

  setProjectFile: (filePath, projectName) => {
    set({
      filePath,
      projectName: projectName ?? (filePath ? basename(filePath) : get().projectName),
      yamlDirty: false,
    })
  },

  openHome: () => {
    clearSimForProjectSwitch()
    set({
      projectId: newProjectId(),
      phase: 'home',
      projectKind: 'none',
      projectName: '',
      filePath: '',
      yamlText: '',
      yamlDirty: false,
      yamlError: null,
      lastDraftSimPath: null,
    })
  },

  openWorkspace: (opts) => {
    clearSimForProjectSwitch()
    const filePath = opts?.filePath !== undefined ? opts.filePath : get().filePath
    const projectName =
      opts?.projectName ??
      (filePath ? basename(filePath) : get().projectName || '未命名工程')
    set({
      projectId: newProjectId(),
      phase: 'workspace',
      editorTab: opts?.editorTab ?? get().editorTab,
      simTab: opts?.simTab ?? get().simTab,
      projectKind: opts?.projectKind ?? get().projectKind,
      projectName,
      filePath: filePath ?? '',
      lastDraftSimPath: null,
    })
  },
}))
