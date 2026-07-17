import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useCanvasStore } from '../store/useCanvasStore'
import type { BlockNodeType } from '../types/canvas'

export function BlockNode({ id, data, selected }: NodeProps<BlockNodeType>) {
  const component = useCanvasStore((s) => s.componentMap[data.type])
  const setSelected = useCanvasStore((s) => s.setSelected)

  if (!component) return null

  const connectableInputs = component.inputs.filter((i) => i.connectable)
  const maxRows = Math.max(connectableInputs.length, component.outputs.length)

  return (
    <div
      className={`rounded-md border bg-card/90 shadow-sm backdrop-blur-sm transition-shadow ${
        selected ? 'border-primary ring-1 ring-primary/30' : 'border-border'
      }`}
      style={{ width: 160 }}
      onClick={() => setSelected(id)}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-2 py-1">
        <span className="text-xs font-medium">{data.name}</span>
        <div className="flex items-center gap-0.5">
          {data.executeFirst && (
            <span className="text-xs text-primary" title="execute_first">⚡</span>
          )}
          <span className="rounded bg-secondary px-1 py-0.5 text-[10px] text-muted-foreground">
            {component.displayName}
          </span>
        </div>
      </div>

      {/* Ports */}
      <div className="px-1.5 py-1">
        {Array.from({ length: maxRows }).map((_, i) => {
          const input = connectableInputs[i]
          const output = component.outputs[i]
          return (
            <div key={i} className="flex items-center justify-between" style={{ minHeight: 18 }}>
              {/* Input port (left) */}
              <div className="relative flex-1">
                {input && (
                  <>
                    <Handle
                      type="target"
                      position={Position.Left}
                      id={input.name}
                      className="!h-2 !w-2 !border !border-background !bg-muted-foreground"
                      style={{ left: -8 }}
                    />
                    <span className="ml-2 text-[10px] text-muted-foreground">
                      {input.name}
                    </span>
                  </>
                )}
              </div>

              {/* Output port (right) */}
              <div className="relative flex-1 text-right">
                {output && (
                  <>
                    <span className="mr-2 text-[10px] text-muted-foreground">
                      {output.name}
                    </span>
                    <Handle
                      type="source"
                      position={Position.Right}
                      id={output.name}
                      className="!h-2 !w-2 !border !border-background !bg-primary"
                      style={{ right: -8 }}
                    />
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
