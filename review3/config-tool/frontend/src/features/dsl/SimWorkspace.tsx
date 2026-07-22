/**
 * DSL 工程仿真区：仿真运行 | 结果趋势 | 导出
 */
import type { DslSimTab } from '../app/navigation'
import { GenericSimTrendPanel } from './GenericSimTrendPanel'
import { SimControlPanel } from './SimControlPanel'
import { SimExportPanel } from './SimExportPanel'
import { useDslProjectStore } from './useDslProjectStore'

const SIM_TABS: Array<{ id: DslSimTab; label: string }> = [
  { id: 'run', label: '仿真运行' },
  { id: 'trend', label: '结果趋势' },
  { id: 'export', label: '导出' },
]

export function SimWorkspace() {
  const simTab = useDslProjectStore((s) => s.simTab)
  const setSimTab = useDslProjectStore((s) => s.setSimTab)

  const active: DslSimTab =
    simTab === 'control' || simTab === 'batch' ? 'run' : simTab === 'trend' || simTab === 'export' ? simTab : 'run'

  return (
    <div className="flex h-full min-h-0 flex-col border-t border-border" data-testid="sim-workspace">
      <div className="flex items-center gap-1 border-b border-border px-2 py-1">
        {SIM_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSimTab(t.id)}
            className={`rounded-md px-2.5 py-1 text-xs ${
              active === t.id
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-secondary'
            }`}
            data-testid={`sim-tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {active === 'run' ? <SimControlPanel /> : null}
        {active === 'trend' ? <GenericSimTrendPanel /> : null}
        {active === 'export' ? <SimExportPanel /> : null}
      </div>
    </div>
  )
}
