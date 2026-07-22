import { create } from 'zustand'
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type Connection,
} from '@xyflow/react'
import { config } from '../../wailsjs/go/models'
import { componentApi, systemApi } from '../lib/api'
import type { BlockNodeData } from '../types/canvas'
import { legacyRedirect } from '../features/app/navigation'
import { useDslProjectStore } from '../features/dsl/useDslProjectStore'

type BlockNode = Node<BlockNodeData, 'block'>

interface CanvasStore {
  components: config.ComponentMeta[]
  componentMap: Record<string, config.ComponentMeta>
  nodes: BlockNode[]
  edges: Edge[]
  selectedNodeId: string | null
  clockMode: string
  cycleTime: number
  loading: boolean

  // 顶层导航：dsl / realtime 为主；旧值保留并在 setView 中重定向
  view: 'config' | 'system' | 'simulation' | 'template' | 'dsl' | 'realtime'
  dfPath: string
  configs: string[]
  dfStatus: { running: boolean; pid: number; configPath: string; mode: string; cycleTime: number; port: number; apiHost?: string; apiPort?: number; runtimeName?: string; apiReady?: boolean }
  dfLogs: string[]

  init: () => void
  addNode: (type: string, position: { x: number; y: number }) => void
  updateNodeData: (id: string, updates: Partial<BlockNodeData>) => void
  onNodesChange: (changes: NodeChange[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => void
  setSelected: (id: string | null) => void
  clear: () => void
  loadCanvasState: (state: config.CanvasState) => void
  getCanvasState: () => config.CanvasState

  setView: (view: 'config' | 'system' | 'simulation' | 'template' | 'dsl' | 'realtime') => void
  setDfPath: (path: string) => void
  setConfigs: (configs: string[]) => void
  setDfStatus: (status: any) => void
  addDfLog: (log: string) => void
  clearDfLogs: () => void
  refreshConfigs: () => void
  refreshStatus: () => void
}

function generateName(type: string, existing: string[]): string {
  const prefix = type.toLowerCase()
  let n = 1
  let name = `${prefix}_${n}`
  while (existing.includes(name)) {
    n++
    name = `${prefix}_${n}`
  }
  return name
}

function defaultParams(meta: config.ComponentMeta): Record<string, any> {
  const params: Record<string, any> = {}
  for (const p of meta.params) {
    params[p.name] = p.default
  }
  return params
}

export const useCanvasStore = create<CanvasStore>((set, get) => ({
  components: [],
  componentMap: {},
  nodes: [],
  edges: [],
  selectedNodeId: null,
  clockMode: 'REALTIME',
  cycleTime: 0.5,
  loading: true,

  view: 'dsl',
  dfPath: '',
  configs: [],
  dfStatus: { running: false, pid: 0, configPath: '', mode: '', cycleTime: 0, port: 0 },
  dfLogs: [],

  init: () => {
    componentApi.list().then((components) => {
      const map: Record<string, config.ComponentMeta> = {}
      for (const c of components) {
        map[c.type] = c
      }
      set({ components, componentMap: map, loading: false })
    }).catch((e) => {
      console.error('Failed to load components:', e)
      set({ loading: false })
    })
  },

  addNode: (type, position) => {
    const meta = get().componentMap[type]
    if (!meta) return
    const existing = get().nodes.map((n) => n.data.name)
    const name = generateName(type, existing)
    const newNode: BlockNode = {
      id: name,
      type: 'block',
      position,
      data: {
        name,
        type,
        params: defaultParams(meta),
        executeFirst: false,
      },
    }
    set({ nodes: [...get().nodes, newNode] })
  },

  updateNodeData: (id, updates) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...updates } } : n
      ),
    })
  },

  onNodesChange: (changes) => {
    const nextNodes = applyNodeChanges(changes, get().nodes) as BlockNode[]
    const removedIds = changes
      .filter((c) => c.type === 'remove')
      .map((c) => (c as { id: string }).id)
    const nextEdges =
      removedIds.length > 0
        ? get().edges.filter(
            (e) => !removedIds.includes(e.source) && !removedIds.includes(e.target)
          )
        : get().edges
    const nextSelected =
      removedIds.includes(get().selectedNodeId || '')
        ? null
        : get().selectedNodeId
    set({ nodes: nextNodes, edges: nextEdges, selectedNodeId: nextSelected })
  },

  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges) })
  },

  onConnect: (connection) => {
    if (!connection.source || !connection.target) return
    if (connection.source === connection.target) return
    const sourceHandle = connection.sourceHandle || ''
    const targetHandle = connection.targetHandle || ''
    const filtered = get().edges.filter(
      (e) =>
        !(
          e.target === connection.target &&
          e.targetHandle === connection.targetHandle
        )
    )
    const newEdge: Edge = {
      source: connection.source,
      target: connection.target,
      sourceHandle: sourceHandle || undefined,
      targetHandle: targetHandle || undefined,
      id: `${connection.source}.${sourceHandle}-${connection.target}.${targetHandle}`,
    }
    set({ edges: addEdge(newEdge, filtered) })
  },

  setSelected: (id) => set({ selectedNodeId: id }),

  clear: () => set({ nodes: [], edges: [], selectedNodeId: null }),

  loadCanvasState: (state) => {
    const nodes: BlockNode[] = (state.nodes || []).map((n) => ({
      id: n.name,
      type: 'block' as const,
      position: { x: n.position?.x || 0, y: n.position?.y || 0 },
      data: {
        name: n.name,
        type: n.type,
        params: n.params || {},
        executeFirst: n.executeFirst,
      },
    }))
    const edges: Edge[] = (state.edges || []).map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourcePort || undefined,
      targetHandle: e.targetPort || undefined,
    }))
    const clockMode = state.clock?.mode || 'REALTIME'
    const cycleTime = state.clock?.cycleTime || 0.5
    set({ nodes, edges, selectedNodeId: null, clockMode, cycleTime })
  },

  getCanvasState: () => {
    const { nodes, edges, clockMode, cycleTime } = get()
    const nameById: Record<string, string> = {}
    for (const n of nodes) {
      nameById[n.id] = n.data.name
    }
    return {
      clock: { mode: clockMode, cycleTime },
      nodes: nodes.map((n) => ({
        id: n.id,
        name: n.data.name,
        type: n.data.type,
        position: n.position,
        params: n.data.params,
        executeFirst: n.data.executeFirst,
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: nameById[e.source] || e.source,
        sourcePort: e.sourceHandle || '',
        target: nameById[e.target] || e.target,
        targetPort: e.targetHandle || '',
      })),
    } as config.CanvasState
  },

  setView: (view) => {
    // Legacy redirects → primary surfaces (no blank pages).
    if (view === 'system') {
      set({ view: 'realtime' })
      return
    }
    if (view === 'template' || view === 'simulation' || view === 'config') {
      const hint = legacyRedirect(view)
      useDslProjectStore.getState().openWorkspace({
        editorTab: hint.editorTab,
        simTab: hint.simTab,
        projectKind: view === 'template' ? 'template' : useDslProjectStore.getState().projectKind || 'template',
      })
      set({ view: 'dsl' })
      return
    }
    set({ view })
  },

  setDfPath: (path) => set({ dfPath: path }),

  setConfigs: (configs) => set({ configs }),

  setDfStatus: (status) => set({ dfStatus: status }),

  addDfLog: (log) => {
    const logs = get().dfLogs
    set({ dfLogs: [...logs.slice(-200), log] })
  },

  clearDfLogs: () => set({ dfLogs: [] }),

  refreshConfigs: () => {
    systemApi.listConfigs().then((configs) => {
      set({ configs: configs || [] })
    }).catch(console.error)
  },

  refreshStatus: () => {
    systemApi.status().then((status: any) => {
      set({ dfStatus: status })
    }).catch(console.error)
  },
}))
