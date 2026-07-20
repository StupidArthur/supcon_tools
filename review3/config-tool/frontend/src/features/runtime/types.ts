// 实时运行时数据类型（阶段 4）
//
// - RuntimeSnapshot 与 Engine snapshot 完全对应（仅字段语义）。
// - 真实 Engine snapshot key 使用 `instance.attribute`（例如 `valve_1.current_opening`）；
//   这里的 camelCase 是为了 UI 绑定方便，runtimeApi 在边界做一次映射。
// - ConnectionState 表示 WebSocket 生命周期；Stale 表示"长时间未收到真实 snapshot"。

export type ConnectionState =
  | 'idle'       // 未启动
  | 'connecting' // 正在连接 / 重连
  | 'connected'  // 已连接
  | 'disconnected' // 已断开，准备重连
  | 'error'      // 错误（不再自动重连）

// RuntimeSnapshot 字段必须与 contracts.md §9.3 中的 snapshot 必需位号保持兼容。
// 任何缺失字段必须保持 undefined，由 selectRuntimeValue 显示 `—` 与告警。
// 重要：cycleCount / simTime 是 optional。
//  - snapshot 中确实包含 → 数字
//  - snapshot 中缺失 → undefined，绝不替换为 0（与"未运行 cycle=0"区分）
export interface RuntimeSnapshot {
  cycleCount?: number
  simTime?: number
  sourceFlow?: number

  valve: {
    targetOpening?: number
    currentOpening?: number
    inletFlow?: number
    outletFlow?: number
  }

  tank1: {
    level?: number
    inletFlow?: number
    outletFlow?: number
  }

  tank2: {
    level?: number
    inletFlow?: number
    outletFlow?: number
  }

  pid: {
    PV?: number
    SV?: number
    CSV?: number
    MV?: number
    PB?: number
    TI?: number
    TD?: number
    KD?: number
    MODE?: number
    SWPN?: number
  }

  // 内部元数据，便于 stale 计算与时间显示
  _receivedAt: number // Date.now()
}

// API 响应形状（后端字段为 snake_case / dashed）
export interface ApiStatusResponse {
  instance_name: string
  mode: string
  cycle_count: number
  sim_time: number
  cycle_time: number
  safe_state: boolean
  consecutive_failures: number
}

export interface ApiMetaResponse {
  instance_name: string
  meta: Record<string, { instance: string; param: string; description: string; is_display: boolean; plot_scale_ref: number }>
  statistics: Record<string, unknown>
}

export type ApiSnapshot = Record<string, number | string | boolean>

// 选择函数返回的统一形态：number | null。
//   null 表示字段缺失（不要返回 0 / undefined / NaN 来假装有值）。
export type RuntimeNumber = number | null

export interface RuntimeValueMeta {
  value: RuntimeNumber
  // 字段是否存在于 snapshot
  present: boolean
  // 字段是否为有限值
  finite: boolean
}