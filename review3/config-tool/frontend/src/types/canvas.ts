import type { Node } from '@xyflow/react'

export interface BlockNodeData extends Record<string, unknown> {
  name: string
  type: string
  params: Record<string, any>
  executeFirst: boolean
}

export type BlockNodeType = Node<BlockNodeData, 'block'>
