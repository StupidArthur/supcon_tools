/**
 * Lightweight DSL project UI store (presentation / navigation only).
 */
import { create } from 'zustand'
import type { DslEditorTab, DslPhase, DslSimTab } from '../app/navigation'

export type DslProjectKind = 'none' | 'template' | 'generic'

interface DslProjectState {
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

export const useDslProjectStore = create<DslProjectState>((set, get) => ({
  phase: 'home',
  editorTab: 'template',
  simTab: 'control',
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
  setYamlText: (yamlText, dirty = true) => set({ yamlText, yamlDirty: dirty, yamlError: null }),
  setYamlError: (yamlError) => set({ yamlError }),
  setLastDraftSimPath: (lastDraftSimPath) => set({ lastDraftSimPath }),

  pushRecent: (path) => {
    if (!path) return
    const next = [path, ...get().recentPaths.filter((p) => p !== path)].slice(0, MAX_RECENT)
    saveRecent(next)
    set({ recentPaths: next })
  },

  openHome: () =>
    set({
      phase: 'home',
      projectKind: 'none',
      projectName: '',
      filePath: '',
      yamlDirty: false,
      yamlError: null,
    }),

  openWorkspace: (opts) => {
    const filePath = opts?.filePath ?? get().filePath
    const projectName =
      opts?.projectName ??
      (filePath ? basename(filePath) : get().projectName || '未命名工程')
    set({
      phase: 'workspace',
      editorTab: opts?.editorTab ?? get().editorTab,
      simTab: opts?.simTab ?? get().simTab,
      projectKind: opts?.projectKind ?? get().projectKind,
      projectName,
      filePath,
    })
  },
}))
