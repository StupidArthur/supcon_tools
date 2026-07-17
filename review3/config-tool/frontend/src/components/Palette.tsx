import { useCanvasStore } from '../store/useCanvasStore'

const categoryLabels: Record<string, string> = {
  algorithm: '算法',
  model: '模型',
  variable: '变量',
}

const categoryOrder = ['algorithm', 'model', 'variable']

export function Palette() {
  const components = useCanvasStore((s) => s.components)
  const loading = useCanvasStore((s) => s.loading)

  if (loading) {
    return (
      <div className="w-48 shrink-0 border-r border-border bg-card p-2.5">
        <div className="text-xs text-muted-foreground">加载组件中...</div>
      </div>
    )
  }

  const grouped = components.reduce((acc, c) => {
    if (!acc[c.category]) acc[c.category] = []
    acc[c.category].push(c)
    return acc
  }, {} as Record<string, typeof components>)

  return (
    <div className="w-48 shrink-0 overflow-y-auto border-r border-border bg-card p-2.5">
      <div className="space-y-3">
        {categoryOrder
          .filter((cat) => grouped[cat])
          .map((category) => (
            <div key={category}>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                {categoryLabels[category] || category}
              </div>
              <div className="space-y-1">
                {grouped[category].map((c) => (
                  <div
                    key={c.type}
                    className="cursor-grab rounded border border-border bg-background px-2 py-1 text-xs transition-colors hover:border-primary hover:bg-secondary active:cursor-grabbing"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('application/reactflow', c.type)
                      e.dataTransfer.effectAllowed = 'move'
                    }}
                  >
                    {c.displayName}
                  </div>
                ))}
              </div>
            </div>
          ))}
      </div>
    </div>
  )
}
