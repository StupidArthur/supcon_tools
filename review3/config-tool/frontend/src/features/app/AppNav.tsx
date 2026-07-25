/**
 * Top navigation: DataFactory | 组态调试 | 工程组态 | 实时运行
 */
import { useCanvasStore } from '../../store/useCanvasStore'
import { resolvePrimaryView, type AppView } from '../app/navigation'
import { useDslProjectStore } from '../dsl/useDslProjectStore'

export function AppNav() {
  const view = useCanvasStore((s) => s.view) as AppView
  const setView = useCanvasStore((s) => s.setView)
  const primary = resolvePrimaryView(view)
  const openHome = useDslProjectStore((s) => s.openHome)

  const goDsl = () => setView('dsl')
  const goProjectConfig = () => setView('project-config')
  const goRealtime = () => setView('realtime-run')

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
      <nav className="flex items-center gap-1" data-testid="app-nav-tabs">
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
          组态调试
        </button>
        <button
          type="button"
          onClick={goProjectConfig}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            primary === 'project-config'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
          data-testid="nav-project-config"
        >
          工程组态
        </button>
        <button
          type="button"
          onClick={goRealtime}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            primary === 'realtime-run'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
          data-testid="nav-realtime"
        >
          实时运行
        </button>
      </nav>
    </header>
  )
}