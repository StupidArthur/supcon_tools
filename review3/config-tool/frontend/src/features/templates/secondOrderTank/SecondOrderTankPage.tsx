import { useEffect, useMemo } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import { RuntimeToolbar } from '../RuntimeToolbar'
import { ObjectInspector } from '../ObjectInspector'
import { SecondOrderTankDiagram } from './SecondOrderTankDiagram'
import { PidFaceplateHost } from './PidFaceplateHost'
import { RuntimeTrendPanel } from './RuntimeTrendPanel'
import { BatchPanelHost } from './BatchPanelHost'
import { bindWritebackRuntime } from './writeback'
import { bindSaveAs } from './saveAs'
import { bindValidateConfig } from './validation'
import { validateConfig } from './validationRules'
import { templateApi } from '../../../lib/api'

// SecondOrderTankPage 是二阶水箱模板的主页面。
// 阶段 2：固定 SVG P&ID + 右侧检查器。
// 阶段 4：现场组件直接订阅 runtime store。
// 阶段 5：PidFaceplate 原子写 + writeback 绑定。
// 阶段 6：RuntimeTrendPanel 趋势 / 事件 / 控制品质。
export function SecondOrderTankPage() {
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
    if (!draft) {
      loadBuiltin().catch((err) => {
        console.warn('加载模板失败:', err)
      })
    }
  }, [draft, loadBuiltin])

  if (!draft) {
    return (
      <div className="flex flex-1 items-center justify-center bg-background p-6 text-xs text-muted-foreground">
        正在加载模板…
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="second-order-tank-page">
      <RuntimeToolbar />

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
        </main>

        <aside
          className="w-80 shrink-0 border-l border-border bg-card overflow-hidden flex flex-col"
          data-testid="inspector-panel"
        >
          <div className="min-h-0 flex-1 overflow-auto">
            <ObjectInspector />
          </div>
          <PidFaceplateHost />
          <BatchPanelHost />
        </aside>
      </div>
    </div>
  )
}
