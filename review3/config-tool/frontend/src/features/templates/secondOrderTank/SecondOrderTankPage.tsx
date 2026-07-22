/**
 * SecondOrderTankPage — 二阶水箱模板主页面。
 * embedded=true 时隐藏 RuntimeToolbar / 趋势 / Batch（由 DSL 工作区承载）。
 */
import { useEffect, useMemo } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import { RuntimeToolbar } from '../RuntimeToolbar'
import { ObjectInspector } from '../ObjectInspector'
import { SecondOrderTankDiagram } from './SecondOrderTankDiagram'
import { PidFaceplateHost } from './PidFaceplateHost'
import { RuntimeTrendPanel } from './RuntimeTrendPanel'
import { BatchPanelHost } from './BatchPanelHost'
import {
  SelectedObjectMessage,
  shouldShowPidControlPanel,
} from './SelectedObjectPanel'
import { bindWritebackRuntime } from './writeback'
import { bindSaveAs } from './saveAs'
import { bindValidateConfig } from './validation'
import { validateConfig } from './validationRules'
import { templateApi } from '../../../lib/api'

export function SecondOrderTankPage({ embedded = false }: { embedded?: boolean }) {
  const draft = useTemplateStore((s) => s.draft)
  const selectedObjectId = useTemplateStore((s) => s.selectedObjectId)
  const selectObject = useTemplateStore((s) => s.selectObject)
  const loadBuiltin = useTemplateStore((s) => s.loadBuiltin)

  const trendBuffer = useRuntimeStore((s) => s.trendBuffer)
  const previousRunSeries = useRuntimeStore((s) => s.previousRunSeries)
  const writeEvents = useRuntimeStore((s) => s.writeEvents)
  const stale = useRuntimeStore((s) => s.stale)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const quality = useRuntimeStore((s) => s.quality)
  const latestSnapshot = useRuntimeStore((s) => s.latestSnapshot)
  const recomputeQuality = useRuntimeStore((s) => s.recomputeQuality)

  const series = useMemo(() => trendBuffer.toArray(), [trendBuffer, latestSnapshot])

  useEffect(() => {
    bindWritebackRuntime({
      store: {
        getState: () => useTemplateStore.getState(),
        setState: (partial) => useTemplateStore.setState(partial as never),
      },
      applyRuntimeOverrides: (req) => templateApi.applyRuntimeOverrides(req),
    })
    bindValidateConfig((doc) => validateConfig(doc as Parameters<typeof validateConfig>[0]))
    bindSaveAs(async (path: string) => {
      return useTemplateStore.getState().save({ targetPath: path, allowOverwrite: true })
    })
  }, [])

  useEffect(() => {
    if (series.length > 0) {
      recomputeQuality()
    }
  }, [series.length, writeEvents.length, recomputeQuality])

  useEffect(() => {
    if (!draft && !embedded) {
      loadBuiltin().catch((err) => {
        console.warn('加载模板失败:', err)
      })
    }
  }, [draft, loadBuiltin, embedded])

  if (!draft) {
    return (
      <div className="flex flex-1 items-center justify-center bg-background p-6 text-xs text-muted-foreground">
        正在加载模板…
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="second-order-tank-page">
      {!embedded ? <RuntimeToolbar /> : null}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <main
          className="min-w-0 flex-1 overflow-hidden bg-background flex flex-col"
          data-testid="diagram-area"
        >
          <div className="min-h-0 flex-1 p-2">
            <SecondOrderTankDiagram
              draft={draft}
              selectedObjectId={selectedObjectId}
              onSelect={selectObject}
            />
          </div>
          {!embedded ? (
            <div className="max-h-[40%] shrink-0 overflow-auto border-t border-border">
              <RuntimeTrendPanel
                series={series}
                previousRunSeries={previousRunSeries}
                events={writeEvents}
                stale={stale}
                connectionState={connectionState}
                quality={quality}
              />
            </div>
          ) : null}
        </main>

        <aside
          className="w-80 shrink-0 border-l border-border bg-card overflow-hidden flex flex-col"
          data-testid="inspector-panel"
          style={{ background: '#FFFFFF' }}
        >
          <SelectedObjectMessage selectedObjectId={selectedObjectId} />
          <div className="min-h-0 flex-1 overflow-auto" data-testid="object-property-panel">
            <ObjectInspector />
            {shouldShowPidControlPanel(selectedObjectId) ? (
              <div className="border-t border-border" data-testid="pid-control-panel">
                <PidFaceplateHost />
              </div>
            ) : null}
          </div>
          {!embedded ? <BatchPanelHost /> : null}
        </aside>
      </div>
    </div>
  )
}
