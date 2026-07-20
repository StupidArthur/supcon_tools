import { useEffect } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { RuntimeToolbar } from '../RuntimeToolbar'
import { ObjectInspector } from '../ObjectInspector'
import { SecondOrderTankDiagram } from './SecondOrderTankDiagram'

// SecondOrderTankPage 是二阶水箱模板的主页面。
// 阶段 2 实现：固定 SVG P&ID + 右侧检查器。
// 阶段 4 扩展：现场组件直接订阅 runtime store，避免复制状态产生跨代数据。
export function SecondOrderTankPage() {
  const draft = useTemplateStore((s) => s.draft)
  const selectedObjectId = useTemplateStore((s) => s.selectedObjectId)
  const selectObject = useTemplateStore((s) => s.selectObject)
  const loadBuiltin = useTemplateStore((s) => s.loadBuiltin)

  useEffect(() => {
    if (!draft) {
      loadBuiltin().catch((err) => {
        console.warn('加载内置模板失败:', err)
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
      {/* 顶部工具栏 */}
      <RuntimeToolbar />

      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 中央 SVG P&ID */}
        <main className="min-w-0 flex-1 overflow-hidden bg-background" data-testid="diagram-area">
          <div className="h-full w-full p-2">
            <SecondOrderTankDiagram
              draft={draft}
              selectedObjectId={selectedObjectId}
              onSelect={selectObject}
            />
          </div>
        </main>

        {/* 右侧检查器 */}
        <aside className="w-80 shrink-0 border-l border-border bg-card overflow-hidden" data-testid="inspector-panel">
          <ObjectInspector />
        </aside>
      </div>
    </div>
  )
}
