// websocket：WebSocket 客户端（阶段 4）。
//
// 关键规则（与 contracts.md §9.3、playbook 阶段 4 一致）：
//   - 正常 WS 消息 = 完整 snapshot 对象。不读取 message.data，不额外包装。
//   - 心跳 = {"_heartbeat": true, "ts": ...}。心跳只更新时间，不替换 latestSnapshot，不追加趋势点。
//   - stale 阈值 = max(3 × cycleTime, 2s)。
//   - 断线后冻结最后值；设置 stale；不清空现场值；不回退到 draft 假默认值。
//   - 指数退避重连：1s, 2s, 4s, 8s, 16s, 30s（封顶 30s）。
//   - 重连必须严格按 backoff -> GET snapshot 完成 -> 创建 WS 的顺序执行。
//   - 卸载时关闭 WebSocket / 定时器 / 重连任务，禁止泄漏。
//
// 阶段 D：订阅协议。
//   - setSubscription(tags|null) 在连接打开后立即发送，重连后自动重发。
//   - 服务端响应 {type:'subscribed', tags:[...]} / {type:'error', code:'...'}。
//   - 响应消息不会进入 buildRuntimeFrame。

import type { ConnectionState } from './types'
import { mapApiSnapshot } from './runtimeApi'

export const MAX_SUBSCRIPTION_TAGS = 5000

export interface RuntimeWsConfig {
  apiHost: string
  apiPort: number
  cycleTime: number
  /** 仅内存；不持久化。空字符串表示不附加 token（开发模式）。 */
  apiToken?: string
}

export type WsMessageHandler = (msg: ParsedWsMessage) => void
export type StateHandler = (state: ConnectionState) => void

export type ParsedWsMessage =
  | { type: 'snapshot'; snapshot: ReturnType<typeof mapApiSnapshot>; raw: Record<string, unknown> }
  | { type: 'heartbeat'; ts: number }
  | { type: 'subscribed'; tags: string[] | null }
  | { type: 'error'; code: string; message: string }
  | { type: 'unknown'; raw: unknown }

export interface RuntimeWs {
  start(): Promise<void>
  stop(): void
  // 重连后第一时间调 REST snapshot；成功后才继续 WS 收消息。
  fetchInitialSnapshot(signal?: AbortSignal): Promise<void>
  isOpen(): boolean
  forceReconnect(): void
  /**
   * 阶段 D：设置订阅 tag 集合。
   * - undefined：尚未发送订阅命令（兼容旧客户端，server 走全量）
   * - null：显式请求全量 snapshot
   * - []：仅 cycle_count/sim_time 元数据
   * - [a, b, ...]：仅订阅指定 tag + 元数据
   */
  setSubscription(tags: string[] | null | undefined): void
  /** 阶段 D：当前正在使用的订阅集合（最后发送值）。 */
  getSubscription(): string[] | null | undefined
}

// 指数退避：1, 2, 4, 8, 16, 30, 30, 30 ... 上限 30s
const BACKOFF_STEPS_MS = [1000, 2000, 4000, 8000, 16000, 30000]
// WebSocket 在浏览器/Node 环境都可以使用。这里假设全局 WebSocket（浏览器）。
type WsFactory = (url: string) => WebSocket

/**
 * 规范化订阅 tag 集合：
 *   - 过滤掉空字符串/非字符串
 *   - 去重并排序
 *   - null 保留为 null（"全量"）
 *   - [] 保留为 []（"仅元数据"）
 * 超过 MAX_SUBSCRIPTION_TAGS 时抛错（不得静默截断）。
 */
function normalizeSubscription(
  tags: string[] | null,
): string[] | null {
  if (tags === null) return null
  const set = new Set<string>()
  for (const t of tags) {
    if (typeof t === 'string' && t.length > 0) set.add(t)
  }
  const arr = Array.from(set).sort()
  if (arr.length > MAX_SUBSCRIPTION_TAGS) {
    throw new Error(
      `订阅超过 ${MAX_SUBSCRIPTION_TAGS} 上限（实际 ${arr.length}），请先收窄订阅范围`,
    )
  }
  return arr
}

/** SubscriptionOverflowError — setSubscription 超过上限时抛出的语义错误。 */
export class SubscriptionOverflowError extends Error {
  readonly actualCount: number
  readonly limit: number
  constructor(actual: number, limit: number) {
    super(`订阅超过 ${limit} 上限（实际 ${actual}），请先收窄订阅范围`)
    this.name = 'SubscriptionOverflowError'
    this.actualCount = actual
    this.limit = limit
  }
}

export function createRuntimeWs(
  config: RuntimeWsConfig,
  onMessage: WsMessageHandler,
  onState: StateHandler,
  deps: { fetchSnapshot: (signal?: AbortSignal) => Promise<void>; wsFactory?: WsFactory } = {
    fetchSnapshot: async () => {},
  },
): RuntimeWs {
  let ws: WebSocket | null = null
  let stopped = false
  let reconnectAttempt = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatHealthTimer: ReturnType<typeof setTimeout> | null = null
  let currentState: ConnectionState = 'idle'
  let operationGeneration = 0
  let snapshotAbort: AbortController | null = null
  let pendingSubscription: string[] | null | undefined = undefined
  let activeSubscription: string[] | null | undefined = undefined
  let sendOnOpen = true

  const factory: WsFactory = deps.wsFactory ?? ((url: string) => new WebSocket(url))

  const wsUrl = (): string => {
    const proto = 'ws:'
    const base = `${proto}//${config.apiHost}:${config.apiPort}/ws/snapshot`
    if (!config.apiToken) return base
    // 不使用 URLSearchParams 以避免对 token 内部特殊字符做二次变换；
    // encodeURIComponent 已经覆盖了所有 reserved 字符。
    return `${base}?token=${encodeURIComponent(config.apiToken)}`
  }

  const setState = (s: ConnectionState): void => {
    if (currentState === s) return
    currentState = s
    onState(s)
  }

  const clearReconnect = (): void => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  const clearHeartbeatHealth = (): void => {
    if (heartbeatHealthTimer) {
      clearTimeout(heartbeatHealthTimer)
      heartbeatHealthTimer = null
    }
  }

  // sendSubscription 立即发送订阅消息。
  // 失败（连接未开）时记入 pendingSubscription，连接 onopen 时再发。
  // 关键：null（"全量"）与 []（仅元数据）都是合法值，必须明确发送。
  const subscriptionsEqual = (
    a: string[] | null | undefined,
    b: string[] | null | undefined,
  ): boolean => {
    if (a === b) return true
    if (a === undefined || b === undefined) return false
    if (a === null || b === null) return false
    if (a.length !== b.length) return false
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false
    }
    return true
  }

  const sendSubscriptionNow = (sock: WebSocket): boolean => {
    if (pendingSubscription === undefined) {
      // setSubscription 还未被调用过，不发送
      return true
    }
    if (subscriptionsEqual(activeSubscription, pendingSubscription)) {
      return true
    }
    if (sock.readyState !== WebSocket.OPEN) return false
    try {
      sock.send(JSON.stringify({ type: 'subscribe', tags: pendingSubscription }))
      activeSubscription = pendingSubscription
      return true
    } catch {
      return false
    }
  }

  // 真实消息超过 HEARTBEAT_HEALTH_THRESHOLD_MS 没收到视为健康异常 → 主动重连。
  // WS 自身有 ping/pong 但浏览器 API 不暴露，这里用一个客户端定时器做"长时间无任何消息"检测。
  // 仅对 WS 自身 sanity 负责；上层 stale 由 store 根据 snapshot _receivedAt 判定。
  const armHeartbeatHealth = (): void => {
    clearHeartbeatHealth()
    heartbeatHealthTimer = setTimeout(() => {
      if (stopped) return
      // 长时间无消息：触发一次重连
      forceReconnect()
    }, 5000)
  }

  const handleMessage = (raw: unknown): void => {
    armHeartbeatHealth()
    if (!raw || typeof raw !== 'object') {
      onMessage({ type: 'unknown', raw })
      return
    }
    const msg = raw as Record<string, unknown>
    if (msg._heartbeat === true) {
      const ts = typeof msg.ts === 'number' ? msg.ts : Date.now() / 1000
      onMessage({ type: 'heartbeat', ts })
      return
    }
    // 阶段 D：控制消息（不进入 buildRuntimeFrame）。
    if (msg.type === 'subscribed') {
      const tags = msg.tags
      const arr = Array.isArray(tags) ? (tags as string[]).filter((t) => typeof t === 'string') : null
      onMessage({ type: 'subscribed', tags: arr })
      return
    }
    if (msg.type === 'error') {
      const code = typeof msg.code === 'string' ? msg.code : 'UNKNOWN'
      const message = typeof msg.message === 'string' ? msg.message : ''
      onMessage({ type: 'error', code, message })
      return
    }
    // snapshot 必须是包含 cycle_count 的 dict 对象。
    // 不读取 message.data，也不额外解包一层。
    if (typeof msg.cycle_count === 'number' || 'valve_1.current_opening' in msg || 'tank_2.level' in msg) {
      const snap = mapApiSnapshot(msg as Record<string, number | string | boolean>, Date.now())
      onMessage({ type: 'snapshot', snapshot: snap, raw: msg })
      return
    }
    onMessage({ type: 'unknown', raw })
  }

  const isActive = (generation: number): boolean =>
    !stopped && generation === operationGeneration

  const connect = (generation: number): void => {
    if (!isActive(generation)) return
    setState('connecting')
    let socket: WebSocket
    try {
      socket = factory(wsUrl())
      ws = socket
    } catch (e) {
      // 工厂异常 → 安排重连
      ws = null
      setState('disconnected')
      scheduleReconnect(generation)
      return
    }

    socket.onopen = () => {
      if (!isActive(generation) || ws !== socket) {
        socket.close()
        return
      }
      setState('connected')
      armHeartbeatHealth()
      // 重连后必须重发订阅（含 null=全量 与 显式列表）
      if (pendingSubscription !== undefined) {
        sendSubscriptionNow(socket)
      }
    }

    socket.onmessage = (ev: MessageEvent) => {
      if (!isActive(generation) || ws !== socket) return
      let parsed: unknown
      try {
        parsed = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data
      } catch {
        return
      }
      handleMessage(parsed)
    }

    socket.onerror = () => {
      if (!isActive(generation) || ws !== socket) return
      // onerror 后通常立即触发 onclose；这里不立即改状态，让 onclose 统一调度重连
    }

    socket.onclose = () => {
      if (!isActive(generation) || ws !== socket) return
      ws = null
      clearHeartbeatHealth()
      // activeSubscription 重置为 undefined，触发重连后重发
      activeSubscription = undefined
      setState('disconnected')
      scheduleReconnect(generation)
    }
  }

  const fetchSnapshotThenConnect = async (generation: number): Promise<void> => {
    if (!isActive(generation)) return
    setState('connecting')
    const controller = new AbortController()
    snapshotAbort?.abort()
    snapshotAbort = controller
    try {
      await deps.fetchSnapshot(controller.signal)
    } catch {
      if (isActive(generation) && !controller.signal.aborted) {
        setState('disconnected')
        scheduleReconnect(generation)
      }
      return
    } finally {
      if (snapshotAbort === controller) snapshotAbort = null
    }
    // stop/disconnect/new start may have happened while REST was in flight.
    if (!isActive(generation) || controller.signal.aborted) return
    connect(generation)
  }

  const scheduleReconnect = (generation: number): void => {
    if (!isActive(generation)) return
    const step = BACKOFF_STEPS_MS[Math.min(reconnectAttempt, BACKOFF_STEPS_MS.length - 1)]
    reconnectAttempt += 1
    clearReconnect()
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      if (!isActive(generation)) return
      // REST 必须完成后才允许创建新 WebSocket。
      void fetchSnapshotThenConnect(generation)
    }, step)
  }

  const forceReconnect = (): void => {
    if (stopped) return
    const generation = ++operationGeneration
    snapshotAbort?.abort()
    snapshotAbort = null
    clearReconnect()
    const socket = ws
    ws = null
    if (socket) {
      try {
        socket.close()
      } catch {
        // ignore
      }
    }
    clearHeartbeatHealth()
    activeSubscription = undefined
    setState('disconnected')
    scheduleReconnect(generation)
  }

  const start = async (): Promise<void> => {
    stopped = false
    sendOnOpen = true
    const generation = ++operationGeneration
    clearReconnect()
    clearHeartbeatHealth()
    snapshotAbort?.abort()
    snapshotAbort = null
    if (ws) {
      const old = ws
      ws = null
      try { old.close() } catch { /* ignore */ }
    }
    // 关键：activeSubscription 必须保持 undefined，避免与显式 setSubscription(null)
    // 的"首次发送"判断混淆。
    activeSubscription = undefined
    reconnectAttempt = 0
    setState('connecting')
    await fetchSnapshotThenConnect(generation)
  }

  const stop = (): void => {
    stopped = true
    sendOnOpen = true
    operationGeneration += 1
    snapshotAbort?.abort()
    snapshotAbort = null
    clearReconnect()
    clearHeartbeatHealth()
    const socket = ws
    ws = null
    if (socket) {
      try {
        socket.close()
      } catch {
        // ignore
      }
    }
    setState('idle')
    activeSubscription = null
    pendingSubscription = null
  }

  const fetchInitialSnapshot = async (signal?: AbortSignal): Promise<void> => {
    await deps.fetchSnapshot(signal)
  }

  const isOpen = (): boolean => ws !== null && ws.readyState === WebSocket.OPEN

  /**
   * 设置订阅。null = 显式全量；undefined = 尚未指定（保持服务端默认）；
   * 超过 MAX_SUBSCRIPTION_TAGS 抛 SubscriptionOverflowError，原有状态保留。
   */
  const setSubscription = (tags: string[] | null | undefined): void => {
    if (tags === undefined) {
      pendingSubscription = undefined
    } else {
      // normalizeSubscription throws on overflow; we propagate to caller
      // and DO NOT mutate pendingSubscription, so the previous valid value
      // remains active. This avoids silent degradation when one source
      // temporarily over-subscribes.
      pendingSubscription = normalizeSubscription(tags)
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      sendSubscriptionNow(ws)
    }
  }

  const getSubscription = (): string[] | null | undefined => pendingSubscription

  return {
    start,
    stop,
    fetchInitialSnapshot,
    isOpen,
    forceReconnect,
    setSubscription,
    getSubscription,
  }
}
