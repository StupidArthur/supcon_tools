import { useCallback } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  useReactFlow,
} from '@xyflow/react'
import { useCanvasStore } from '../store/useCanvasStore'
import { BlockNode } from './BlockNode'

const nodeTypes = { block: BlockNode }

export function Canvas() {
  const { screenToFlowPosition } = useReactFlow()
  const nodes = useCanvasStore((s) => s.nodes)
  const edges = useCanvasStore((s) => s.edges)
  const onNodesChange = useCanvasStore((s) => s.onNodesChange)
  const onEdgesChange = useCanvasStore((s) => s.onEdgesChange)
  const onConnect = useCanvasStore((s) => s.onConnect)
  const setSelected = useCanvasStore((s) => s.setSelected)
  const addNode = useCanvasStore((s) => s.addNode)

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const type = e.dataTransfer.getData('application/reactflow')
      if (!type) return
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      addNode(type, position)
    },
    [screenToFlowPosition, addNode]
  )

  return (
    <div
      className="flex-1"
      onDrop={onDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => setSelected(node.id)}
        onPaneClick={() => setSelected(null)}
        deleteKeyCode={['Delete', 'Backspace']}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  )
}
