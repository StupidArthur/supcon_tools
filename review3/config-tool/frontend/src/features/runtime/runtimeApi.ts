// runtimeApi：纯函数式访问 FastAPI REST 接口（status / meta / snapshot）。
//
// 关键规则：
//   - 必须先调 getStatus() 获取真实 runtimeName，再调 getMeta/getSnapshot。
//   - 任何路径里的 runtimeName 都来自 /api/status.instance_name，禁止硬编码或与 Program 实例名混淆。
//   - 这里不维护业务状态（连接、缓存、心跳），只做 HTTP 调用和字段映射。
//   - REST 鉴权：cfg.apiToken 非空时必须加 Authorization: Bearer <token> 头；
//     空 token 不发送 Authorization（兼容 DATAFACTORY_NO_AUTH 开发模式）。

import type {
  ApiMetaResponse,
  ApiSnapshot,
  ApiStatusResponse,
  RuntimeSnapshot,
} from './types'

export interface RuntimeApiConfig {
  apiHost: string
  apiPort: number
  /** 仅内存；不持久化。空字符串表示不发送 Authorization（如开发模式）。 */
  apiToken?: string
}

export class RuntimeApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'RuntimeApiError'
  }
}

async function fetchJson<T>(url: string, cfg: RuntimeApiConfig, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {}
  if (cfg.apiToken) {
    headers['Authorization'] = `Bearer ${cfg.apiToken}`
  }
  const resp = await fetch(url, { signal, headers })
  if (!resp.ok) {
    throw new RuntimeApiError(resp.status, `${url} → HTTP ${resp.status}`)
  }
  return (await resp.json()) as T
}

function apiUrl(cfg: RuntimeApiConfig, path: string): string {
  return `http://${cfg.apiHost}:${cfg.apiPort}${path}`
}

// getStatus 调用 /api/status；返回的 instance_name 必须用于后续 meta/snapshot 调用。
export async function getStatus(
  cfg: RuntimeApiConfig,
  signal?: AbortSignal,
): Promise<ApiStatusResponse> {
  return fetchJson<ApiStatusResponse>(apiUrl(cfg, '/api/status'), cfg, signal)
}

export async function getMeta(
  cfg: RuntimeApiConfig,
  runtimeName: string,
  signal?: AbortSignal,
): Promise<ApiMetaResponse> {
  return fetchJson<ApiMetaResponse>(
    apiUrl(cfg, `/api/instances/${encodeURIComponent(runtimeName)}/meta`),
    cfg,
    signal,
  )
}

export async function getSnapshot(
  cfg: RuntimeApiConfig,
  runtimeName: string,
  signal?: AbortSignal,
): Promise<ApiSnapshot> {
  return fetchJson<ApiSnapshot>(
    apiUrl(cfg, `/api/instances/${encodeURIComponent(runtimeName)}/snapshot`),
    cfg,
    signal,
  )
}

export interface ApiTagsResponse {
  ok: boolean
  tags: import('./types').RuntimeTagMeta[]
}

export async function getTags(
  cfg: RuntimeApiConfig,
  runtimeName: string,
  signal?: AbortSignal,
): Promise<ApiTagsResponse> {
  return fetchJson<ApiTagsResponse>(
    apiUrl(cfg, `/api/instances/${encodeURIComponent(runtimeName)}/tags`),
    cfg,
    signal,
  )
}

// 把 snake_case API snapshot 映射到 RuntimeSnapshot camelCase 形状。
// 缺失字段保持 undefined，由 selectRuntimeValue 视为 null。
// 严禁把 undefined 替换为 NaN/0：selectRuntimeNumber 会用 Number.isFinite 区分。
//
// 关键约束：cycle_count / sim_time 缺失时**绝不能**映射为 0；这会与
// "Engine 已启动但还没推周期"或"snapshot 字段不完整"两种状态混淆。
// 缺失时保持 undefined，由上层 UI 显示 `—` 和告警。
export function mapApiSnapshot(raw: ApiSnapshot, receivedAt: number): RuntimeSnapshot {
  const num = (k: string): number | undefined => {
    const v = raw[k]
    if (v === undefined || v === null) return undefined
    if (typeof v === 'number') return Number.isFinite(v) ? v : undefined
    const n = Number(v)
    return Number.isFinite(n) ? n : undefined
  }

  return {
    cycleCount: num('cycle_count'),
    simTime: num('sim_time'),
    sourceFlow: num('source_flow'),
    valve: {
      targetOpening: num('valve_1.target_opening'),
      currentOpening: num('valve_1.current_opening'),
      inletFlow: num('valve_1.inlet_flow'),
      outletFlow: num('valve_1.outlet_flow'),
    },
    tank1: {
      level: num('tank_1.level'),
      inletFlow: num('tank_1.inlet_flow'),
      outletFlow: num('tank_1.outlet_flow'),
    },
    tank2: {
      level: num('tank_2.level'),
      inletFlow: num('tank_2.inlet_flow'),
      outletFlow: num('tank_2.outlet_flow'),
    },
    pid: {
      PV: num('pid2.PV'),
      SV: num('pid2.SV'),
      CSV: num('pid2.CSV'),
      MV: num('pid2.MV'),
      PB: num('pid2.PB'),
      TI: num('pid2.TI'),
      TD: num('pid2.TD'),
      KD: num('pid2.KD'),
      MODE: num('pid2.MODE'),
      SWPN: num('pid2.SWPN'),
      SWAM: num('pid2.SWAM'),
      SWSV: num('pid2.SWSV'),
    },
    _receivedAt: receivedAt,
  }
}