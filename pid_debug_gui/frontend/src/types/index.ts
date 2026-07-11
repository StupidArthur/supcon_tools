export interface StatusResponse {
  instance_name: string
  mode: string
  cycle_count: number
  sim_time: number
  safe_state: boolean
  consecutive_failures: number
}

export interface MetaResponse {
  instance_name: string
  meta: Record<string, MetaItem>
  statistics: Record<string, unknown>
}

export interface MetaItem {
  instance: string
  param: string
  description: string
  is_display: boolean
  plot_scale_ref: number
}

export interface DisplayVar {
  name: string
  scale: number
}

export interface SnapshotData {
  cycle_count?: number
  sim_time?: number
  _safe_state?: boolean
  _consecutive_failures?: number
  [key: string]: number | boolean | undefined
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected'
