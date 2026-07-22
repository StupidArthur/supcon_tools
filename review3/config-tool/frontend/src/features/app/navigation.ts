/**
 * App-level navigation state helpers.
 * Primary surfaces: dsl | realtime.
 * Legacy views redirect into the new surfaces (no blank pages).
 */

export type LegacyView = 'config' | 'system' | 'simulation' | 'template'
export type PrimaryView = 'dsl' | 'realtime'
export type AppView = PrimaryView | LegacyView

export type DslPhase = 'home' | 'workspace'
export type DslEditorTab = 'template' | 'yaml' | 'topology'
export type DslSimTab = 'run' | 'trend' | 'export' | 'control' | 'batch'

export function resolvePrimaryView(view: AppView): PrimaryView {
  if (view === 'realtime' || view === 'system') return 'realtime'
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
    case 'system':
    case 'realtime':
      return { primary: 'realtime' }
    case 'simulation':
      return { primary: 'dsl', phase: 'workspace', simTab: 'run' }
    case 'config':
      return { primary: 'dsl', phase: 'workspace', editorTab: 'topology' }
    case 'template':
      return { primary: 'dsl', phase: 'workspace', editorTab: 'template' }
    case 'dsl':
    default:
      return { primary: 'dsl' }
  }
}
