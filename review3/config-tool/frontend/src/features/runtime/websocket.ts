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

import type { ConnectionState } from './types'
import { mapApiSnapshot } from './runtimeApi'

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
  | { type: 'unknown'; raw: unknown }

export interface RuntimeWs {
  start(): Promise<void>
  stop(): void
  // 重连后第一时间调 REST snapshot；成功后才继续 WS 收消息。
  fetchInitialSnapshot(signal?: AbortSignal): Promise<void>
  isOpen(): boolean
  forceReconnect(): void
}

// 指数退避：1, 2, 4, 8, 16, 30, 30, 30 ... 上限 30s
const BACKOFF_STEPS_MS = [1000, 2000, 4000, 8000, 16000, 30000]
// WebSocket 在浏览器/Node 环境都可以使用。这里假设全局 WebSocket（浏览器）。
type WsFactory = (url: string) => WebSocket

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
    setState('disconnected')
    scheduleReconnect(generation)
  }

  const start = async (): Promise<void> => {
    stopped = false
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
    reconnectAttempt = 0
    setState('connecting')
    await fetchSnapshotThenConnect(generation)
  }

  const stop = (): void => {
    stopped = true
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
  }

  const fetchInitialSnapshot = async (signal?: AbortSignal): Promise<void> => {
    await deps.fetchSnapshot(signal)
  }

  const isOpen = (): boolean => ws !== null && ws.readyState === WebSocket.OPEN

  return {
    start,
    stop,
    fetchInitialSnapshot,
    isOpen,
    forceReconnect,
  }
}
