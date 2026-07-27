/**
 * 已废弃：请使用 GenericSimPanel。
 * 保留编译占位。
 */
import { useState } from 'react'
import { useCanvasStore } from '../store/useCanvasStore'

export function SimulationPanel() {
  const dfPath = useCanvasStore((s) => s.dfPath)
  const configs = useCanvasStore((s) => s.configs)
  const [selectedConfig, setSelectedConfig] = useState('')
  const [cycles, setCycles] = useState(100)
  return (
    <div className="flex-1 overflow-y-auto bg-background p-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <h2 className="text-lg font-medium">仿真运行（已废弃）</h2>
        <p className="text-xs text-muted-foreground">请使用 DSL 工程页面中的通用仿真面板。</p>
        <div>{dfPath} · {configs.length} configs · {cycles} cycles · {selectedConfig}</div>
      </div>
    </div>
  )
}
