/**
 * App-level navigation state helpers.
 * Primary surfaces: dsl | project-config | realtime-run.
 * Legacy views redirect into the new surfaces (no blank pages).
 */

export type LegacyView = 'config' | 'system' | 'simulation' | 'template' | 'realtime'
export type PrimaryView = 'dsl' | 'project-config' | 'realtime-run'
export type AppView = PrimaryView | LegacyView

export type DslPhase = 'home' | 'workspace'
export type DslEditorTab = 'template' | 'yaml' | 'topology'
export type DslSimTab = 'run' | 'trend' | 'export' | 'control' | 'batch'

export function resolvePrimaryView(view: AppView): PrimaryView {
  if (view === 'project-config') return 'project-config'
  if (view === 'realtime-run') return 'realtime-run'
  if (view === 'realtime' || view === 'system' || view === 'config') return 'project-config'
  // 'dsl' | 'simulation' | 'template' all route to DSL shell.
  return 'dsl'
}

/** Map legacy setView targets to primary + optional workspace hints. */
export function legacyRedirect(view: AppView): {
  primary: PrimaryView
  phase?: DslPhase
  editorTab?: DslEditorTab
  simTab?: DslSimTab
} {
  switch (view) {
    case 'realtime-run':
    case 'realtime':
    case 'system':
    case 'config':
      return { primary: 'project-config' }
    case 'simulation':
      return { primary: 'dsl', phase: 'workspace', simTab: 'run' }
    case 'template':
      return { primary: 'dsl', phase: 'workspace', editorTab: 'template' }
    case 'dsl':
    default:
      return { primary: 'dsl' }
  }
}