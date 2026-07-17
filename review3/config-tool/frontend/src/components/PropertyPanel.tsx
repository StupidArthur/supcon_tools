import { useCanvasStore } from '../store/useCanvasStore'

export function PropertyPanel() {
  const selectedId = useCanvasStore((s) => s.selectedNodeId)
  const nodes = useCanvasStore((s) => s.nodes)
  const edges = useCanvasStore((s) => s.edges)
  const componentMap = useCanvasStore((s) => s.componentMap)
  const updateNodeData = useCanvasStore((s) => s.updateNodeData)

  const node = nodes.find((n) => n.id === selectedId)

  if (!node) {
    return (
      <div className="w-60 shrink-0 overflow-y-auto border-l border-border bg-card p-2.5">
        <div className="text-xs text-muted-foreground">选择节点查看属性</div>
      </div>
    )
  }

  const { name, type, params, executeFirst } = node.data
  const meta = componentMap[type]
  if (!meta) return null

  const isConnected = (paramName: string) =>
    edges.some(
      (e) => e.target === selectedId && e.targetHandle === paramName
    )

  const getSource = (paramName: string) => {
    const edge = edges.find(
      (e) => e.target === selectedId && e.targetHandle === paramName
    )
    if (!edge) return null
    return `${edge.source}.${edge.sourceHandle}`
  }

  const setParam = (key: string, value: any) => {
    updateNodeData(selectedId!, {
      params: { ...params, [key]: value },
    })
  }

  const parseValue = (s: string): any => {
    const n = Number(s)
    return !isNaN(n) && s.trim() !== '' ? n : s
  }

  return (
    <div className="w-60 shrink-0 overflow-y-auto border-l border-border bg-card p-2.5">
      {/* Header */}
      <div className="mb-2 space-y-0.5">
        <div className="text-xs font-medium">{name}</div>
        <div className="text-[10px] text-muted-foreground">
          {meta.displayName} ({type})
        </div>
      </div>

      {/* Execute First */}
      <label className="mb-2 flex items-center gap-1.5 text-xs">
        <input
          type="checkbox"
          checked={executeFirst}
          onChange={(e) =>
            updateNodeData(selectedId!, { executeFirst: e.target.checked })
          }
          className="rounded"
        />
        <span>execute_first</span>
      </label>

      {/* Parameters */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">参数</div>
        {meta.params.map((p) => {
          const connected = isConnected(p.name)
          const source = getSource(p.name)
          const value = params[p.name]
          const displayValue =
            typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')

          return (
            <div key={p.name} className="space-y-0.5">
              <label className="text-xs text-muted-foreground">
                {p.name}
                {p.desc && (
                  <span className="ml-1 text-muted-foreground/60">— {p.desc}</span>
                )}
              </label>
              {connected ? (
                <div className="rounded-md border border-border bg-secondary px-2 py-1 text-xs">
                  ← {source}
                </div>
              ) : (
                <input
                  type="text"
                  value={displayValue}
                  onChange={(e) => setParam(p.name, parseValue(e.target.value))}
                  className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs focus:border-primary focus:outline-none"
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
