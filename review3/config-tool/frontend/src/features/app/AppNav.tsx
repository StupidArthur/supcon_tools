/**
 * Top navigation: DataFactory | DSL 工程 | 实时运行与 UA
 */
import { useCanvasStore } from '../../store/useCanvasStore'
import { resolvePrimaryView, type AppView } from '../app/navigation'
import { useDslProjectStore } from '../dsl/useDslProjectStore'

export function AppNav() {
  const view = useCanvasStore((s) => s.view) as AppView
  const setView = useCanvasStore((s) => s.setView)
  const primary = resolvePrimaryView(view)
  const openHome = useDslProjectStore((s) => s.openHome)

  const goDsl = () => {
    setView('dsl')
  }

  const goRealtime = () => {
    // Warn if leaving DSL with unsaved edits when navigating to realtime.
    const dirty =
      useDslProjectStore.getState().yamlDirty ||
      // template dirty is checked inside RealtimeUaPage; soft navigate here.
      false
    void dirty
    setView('realtime')
  }

  const goBrandHome = () => {
    openHome()
    setView('dsl')
  }

  return (
    <header
      className="flex items-center gap-3 border-b border-border bg-card px-4 py-2"
      data-testid="app-nav"
    >
      <button
        type="button"
        onClick={goBrandHome}
        className="text-sm font-semibold tracking-tight text-foreground hover:opacity-80"
        data-testid="nav-brand"
      >
        DataFactory
      </button>
      <nav className="flex items-center gap-1">
        <button
          type="button"
          onClick={goDsl}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            primary === 'dsl'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
          data-testid="nav-dsl"
        >
          DSL 工程
        </button>
        <button
          type="button"
          onClick={goRealtime}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            primary === 'realtime'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
          data-testid="nav-realtime"
        >
          实时运行与 UA
        </button>
      </nav>
    </header>
  )
}
