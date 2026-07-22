/**
 * DSL 工程仿真区：仿真控制 | 趋势 | Batch | 导出
 */
import { useMemo } from 'react'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { BatchPanelHost } from '../templates/secondOrderTank/BatchPanelHost'
import { RuntimeTrendPanel } from '../templates/secondOrderTank/RuntimeTrendPanel'
import { SimulationPanel } from '../../components/SimulationPanel'
import type { DslSimTab } from '../app/navigation'
import { useDslProjectStore } from './useDslProjectStore'
import { SimControlPanel } from './SimControlPanel'

const SIM_TABS: Array<{ id: DslSimTab; label: string }> = [
  { id: 'control', label: '仿真控制' },
  { id: 'trend', label: '趋势' },
  { id: 'batch', label: 'Batch' },
  { id: 'export', label: '导出' },
]

export function SimWorkspace() {
  const simTab = useDslProjectStore((s) => s.simTab)
  const setSimTab = useDslProjectStore((s) => s.setSimTab)

  const trendBuffer = useRuntimeStore((s) => s.trendBuffer)
  const previousRunSeries = useRuntimeStore((s) => s.previousRunSeries)
  const writeEvents = useRuntimeStore((s) => s.writeEvents)
  const stale = useRuntimeStore((s) => s.stale)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const quality = useRuntimeStore((s) => s.quality)
  const latestSnapshot = useRuntimeStore((s) => s.latestSnapshot)
  const series = useMemo(() => trendBuffer.toArray(), [trendBuffer, latestSnapshot])

  return (
    <div className="flex h-full min-h-0 flex-col border-t border-border" data-testid="sim-workspace">
      <div className="flex items-center gap-1 border-b border-border px-2 py-1">
        {SIM_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSimTab(t.id)}
            className={`rounded-md px-2.5 py-1 text-xs ${
              simTab === t.id
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
        {simTab === 'control' ? <SimControlPanel /> : null}
        {simTab === 'trend' ? (
          <RuntimeTrendPanel
            series={series}
            previousRunSeries={previousRunSeries}
            events={writeEvents}
            stale={stale}
            connectionState={connectionState}
            quality={quality}
          />
        ) : null}
        {simTab === 'batch' ? (
          <div className="p-2">
            <BatchPanelHost />
          </div>
        ) : null}
        {simTab === 'export' ? (
          <div className="p-2" data-testid="sim-export-panel">
            <SimulationPanel />
          </div>
        ) : null}
      </div>
    </div>
  )
}
