// useRuntimeStore：阶段 4 运行时状态。
//
// 职责：
//   - 管理 WebSocket 生命周期（connect/disconnect）。
//   - 保存最新真实 snapshot（latestSnapshot），禁止从 draft 假冒。
//   - 心跳只更新 lastHeartbeatAt，不替换 latestSnapshot、不追加趋势点。
//   - stale 判定：snapshot._receivedAt 距 now 超过 max(3 × cycleTime, 2s)。
//   - 断线冻结最后值，不清空现场值。
//   - 卸载时关闭 WebSocket / 定时器 / 重连任务。
//
// 关键并发安全：
//   - connect() 是 async；disconnect() 可能在其 await 期间调用。
//   - 用 generation token（_connectGeneration）跟踪每次 connect 调用的"代"；
//     任何 await 后都必须检查 generation；若已被新 connect / disconnect 接管，
//     则放弃创建 WS / 写入最新 snapshot 等副作用，避免"晚到事件"覆盖新状态。
//   - disconnect() 同样递增 generation，使正在 await 的 connect 早返回。

import { create } from 'zustand'
import type {
  ConnectionState,
  RuntimeFrame,
  RuntimeSnapshot,
  RuntimeTagMeta,
} from './types'
import { buildRuntimeFrame } from './types'
import {
  getMeta,
  getSnapshot,
  getStatus,
  getTags,
  mapApiSnapshot,
  RuntimeApiError,
} from './runtimeApi'
import {
  computeStaleThresholdMs,
} from './dataSelection'
import { createRuntimeWs, type RuntimeWs } from './websocket'
import type { TrendBuffer, TrendPoint } from './trendBuffer'
import { TrendBuffer as TrendBufferClass } from './trendBuffer'
import { computeControlQuality, type QualitySample } from './controlQuality'

export interface RuntimeWriteEvent {
  id: string
  status: 'pending' | 'applied' | 'failed'
  tag: string
  oldValue: number | null
  newValue: number | null
  source: string
  /** REST 接受时刻（仅表示 pending 创建） */
  restReturnedAt: number
  /** snapshot 全量确认时刻；applied 必须用此值 */
  confirmedAt?: number
}

export interface RuntimeStoreState {
  // 连接状态
  apiHost: string
  apiPort: number
  runtimeName: string | null
  connectionState: ConnectionState
  // API readiness（由 SystemBinding.status().apiReady 写入，REST 真实可达）
  apiReady: boolean
  // Engine 周期时间（来自 /api/status.cycle_time）
  cycleTime: number
  // 最新真实 snapshot
  latestSnapshot: RuntimeSnapshot | null
  rawSnapshot: Record<string, unknown> | null
  // 通用运行帧（阶段 6）：不依赖固定字段
  latestFrame: RuntimeFrame | null
  // 通用 tag catalog（阶段 6）
  tagCatalog: RuntimeTagMeta[]
  snapshotReceivedAt: number | null
  lastHeartbeatAt: number | null
  stale: boolean
  staleThresholdMs: number
  // 趋势缓冲（仅真实 snapshot，不含心跳）
  trendBuffer: TrendBuffer
  trendTags: string[]
  /** 上一次运行归档的趋势点 */
  previousRunSeries: TrendPoint[]
  /** Faceplate / 原子写事件（pending/applied/failed） */
  writeEvents: RuntimeWriteEvent[]
  /** 最近一次控制品质计算结果 */
  quality: Record<string, unknown> | null
  /** 曲线可见性 */
  seriesVisibility: Record<string, boolean>
  // 最近一次错误信息（断线但有真实数据时仍保留 lastGoodSnapshot）
  lastError: string | null
  // 当前活跃的 connect generation；disconnect/重连递增
  connectGeneration: number

  // Actions
  setEndpoint: (host: string, port: number) => void
  setApiReady: (ready: boolean) => void
  setTrendTags: (tags: string[]) => void
  setSeriesVisibility: (tag: string, visible: boolean) => void
  /** 新一次运行开始时归档当前趋势 */
  rotatePreviousRun: () => void
  recordWriteEvent: (event: RuntimeWriteEvent) => void
  updateWriteEvent: (
    id: string,
    patch: Partial<Pick<RuntimeWriteEvent, 'status' | 'confirmedAt'>>,
  ) => void
  recomputeQuality: () => void
  connect: () => Promise<void>
  disconnect: () => void
  // 每秒调用一次检查 stale
  tickStaleCheck: () => void
  // 测试 helper
  _reset: () => void
}

const DEFAULT_API_HOST = '127.0.0.1'
const DEFAULT_API_PORT = 8000

export const useRuntimeStore = create<RuntimeStoreState>((set, get) => {
  let ws: RuntimeWs | null = null
  let staleCheckTimer: ReturnType<typeof setInterval> | null = null

  const startStaleCheck = (): void => {
    if (staleCheckTimer) return
    staleCheckTimer = setInterval(() => {
      get().tickStaleCheck()
    }, 500)
  }

  const stopStaleCheck = (): void => {
    if (staleCheckTimer) {
      clearInterval(staleCheckTimer)
      staleCheckTimer = null
    }
  }

  const doFetchSnapshot = async (
    generation: number,
    endpoint: { apiHost: string; apiPort: number },
    runtimeName: string,
    signal?: AbortSignal,
  ): Promise<void> => {
    try {
      const raw = await getSnapshot(
        endpoint,
        runtimeName,
        signal,
      )
      if (signal?.aborted || get().connectGeneration !== generation) return
      // Engine 尚未产出周期时 REST 返回 {}。它不是一份“新鲜的空快照”，
      // 不得覆盖/刷新上一份真实值，也不得清除 stale。
      if (Object.keys(raw).length === 0) return
      const receivedAt = Date.now()
      const snap = mapApiSnapshot(raw, receivedAt)
      set({
        latestSnapshot: snap,
        snapshotReceivedAt: receivedAt,
        stale: false,
        lastError: null,
      })
    } catch (e) {
      if (signal?.aborted || get().connectGeneration !== generation) return
      const msg = e instanceof RuntimeApiError ? `${e.status} ${e.message}` : String(e)
      set({ lastError: msg })
      throw e
    }
  }

  return {
    apiHost: DEFAULT_API_HOST,
    apiPort: DEFAULT_API_PORT,
    runtimeName: null,
    connectionState: 'idle',
    apiReady: false,
    cycleTime: 0.5,
    latestSnapshot: null,
    rawSnapshot: null,
    latestFrame: null,
    tagCatalog: [],
    snapshotReceivedAt: null,
    lastHeartbeatAt: null,
    stale: false,
    staleThresholdMs: computeStaleThresholdMs(0.5),
    trendBuffer: new TrendBufferClass(),
    trendTags: ['tank_2.level', 'pid2.SV', 'pid2.MV', 'valve_1.current_opening'],
    previousRunSeries: [],
    writeEvents: [],
    quality: null,
    seriesVisibility: {
      'tank_2.level': true,
      'pid2.SV': true,
      'pid2.MV': true,
      'valve_1.current_opening': true,
    },
    lastError: null,
    connectGeneration: 0,

    setEndpoint: (host, port) => set({ apiHost: host, apiPort: port }),
    setApiReady: (ready) => set({ apiReady: ready }),
    setTrendTags: (tags) => {
      set({ trendTags: tags })
    },
    setSeriesVisibility: (tag, visible) => {
      set((prev) => ({
        seriesVisibility: { ...prev.seriesVisibility, [tag]: visible },
      }))
    },
    rotatePreviousRun: () => {
      const archived = get().trendBuffer.rotateOut()
      set({ previousRunSeries: archived, quality: null })
    },
    recordWriteEvent: (event) => {
      set((prev) => ({ writeEvents: [...prev.writeEvents, event] }))
    },
    updateWriteEvent: (id, patch) => {
      set((prev) => ({
        writeEvents: prev.writeEvents.map((ev) =>
          ev.id === id ? { ...ev, ...patch } : ev,
        ),
      }))
    },
    recomputeQuality: () => {
      const points = get().trendBuffer.toArray()
      const samples: QualitySample[] = points.map((p) => ({
        t: typeof p.simTime === 'number' ? p.simTime : 0,
        pv: p.values['tank_2.level'] ?? p.values['pid2.PV'] ?? null,
        sv: p.values['pid2.SV'] ?? null,
        mv: p.values['pid2.MV'] ?? null,
        level: p.values['tank_2.level'] ?? null,
      }))
      const quality = computeControlQuality(samples, {
        errorBand: 0.02,
        stableWindowSeconds: 60,
        mvLow: 0,
        mvHigh: 100,
        levelLow: 0,
        levelHigh: 1.2,
        events: get().writeEvents.filter((e) => e.status === 'applied') as unknown as Array<
          Record<string, unknown>
        >,
      })
      set({ quality })
    },

    connect: async () => {
      // 如果已有 WS，先停掉；递增 generation 让所有进行中的 connect 失效。
      const myGen = (get().connectGeneration ?? 0) + 1
      set({ connectGeneration: myGen })
      if (ws) {
        ws.stop()
        ws = null
      }
      const state = get()

      // 第一步：GET /api/status 获取真实 runtimeName
      let status
      try {
        status = await getStatus({ apiHost: state.apiHost, apiPort: state.apiPort })
      } catch (e) {
        // 若 generation 已变（disconnect 在我们 await 期间发生），不要写错误状态
        if (get().connectGeneration !== myGen) return
        const msg = e instanceof RuntimeApiError ? `${e.status} ${e.message}` : String(e)
        set({ connectionState: 'error', lastError: msg })
        return
      }

      // 第二道闸：若 generation 已变（例如 disconnect/新 connect 接管），不创建 WS。
      if (get().connectGeneration !== myGen) {
        return
      }

      const cycleTime = status.cycle_time > 0 ? status.cycle_time : 0.5
      const runtimeName = status.instance_name

      // 第三步：用真实 runtimeName 调 meta（meta 失败不阻止 WS）
      try {
        await getMeta({ apiHost: state.apiHost, apiPort: state.apiPort }, runtimeName)
      } catch (e) {
        // 忽略
      }

      // 通用 tag catalog（失败不阻止 WS）
      try {
        const tagsResp = await getTags({ apiHost: state.apiHost, apiPort: state.apiPort }, runtimeName)
        if (get().connectGeneration === myGen && Array.isArray(tagsResp.tags)) {
          set({ tagCatalog: tagsResp.tags })
        }
      } catch (e) {
        // 忽略
      }

      // 第三道闸：再次检查 generation，避免 meta 期间被打断
      if (get().connectGeneration !== myGen) {
        return
      }

      set({
        runtimeName,
        cycleTime,
        staleThresholdMs: computeStaleThresholdMs(cycleTime),
      })

      // 第四步：连接 WS；start() 内会先 GET snapshot 再开 WS。
      const endpoint = { apiHost: state.apiHost, apiPort: state.apiPort }
      const runtimeWs = createRuntimeWs(
        { apiHost: state.apiHost, apiPort: state.apiPort, cycleTime },
        (msg) => {
          // 消息回调：仅在 generation 未变时写入 snapshot / heartbeat。
          if (get().connectGeneration !== myGen) return
          if (msg.type === 'snapshot') {
            const frame = buildRuntimeFrame(msg.raw, Date.now())
            set((prev) => {
              prev.trendBuffer.pushFrame(frame, prev.trendTags)
              return {
                latestSnapshot: msg.snapshot,
                rawSnapshot: msg.raw,
                latestFrame: frame,
                snapshotReceivedAt: Date.now(),
                stale: false,
                lastHeartbeatAt: null,
              }
            })
          } else if (msg.type === 'heartbeat') {
            // 心跳：只更新 lastHeartbeatAt，不替换 latestSnapshot，不追加趋势。
            set({ lastHeartbeatAt: Date.now() })
          } else {
            // unknown：忽略
          }
        },
        (connState) => {
          if (get().connectGeneration !== myGen) {
            // 我们已被新 connect / disconnect 接管，不更新连接状态
            return
          }
          set({ connectionState: connState })
          if (connState === 'disconnected') {
            // 断线：冻结最后值并立即标 stale。
            set({ stale: true })
          }
        },
        {
          fetchSnapshot: (signal) =>
            doFetchSnapshot(myGen, endpoint, runtimeName, signal),
        },
      )
      ws = runtimeWs
      startStaleCheck()
      await runtimeWs.start()
      if (get().connectGeneration !== myGen) runtimeWs.stop()
    },

    disconnect: () => {
      // 递增 generation 让所有进行中的 connect 失效。
      const nextGen = (get().connectGeneration ?? 0) + 1
      set({ connectGeneration: nextGen })
      stopStaleCheck()
      if (ws) {
        ws.stop()
        ws = null
      }
      // 按契约：
      // - 冻结最后真实值（不替换、不清空 latestSnapshot）
      // - 设置 stale = true（disconnect 视为断线，无论是否在阈值内）
      // - 不清空 snapshotReceivedAt（保持供 stale 计算）
      set({
        connectionState: 'idle',
        stale: true,
      })
    },

    tickStaleCheck: () => {
      const s = get()
      const receivedAt = s.snapshotReceivedAt
      if (s.connectionState === 'disconnected') {
        if (!s.stale) set({ stale: true })
        return
      }
      if (receivedAt === null) return
      const elapsed = Date.now() - receivedAt
      const shouldStale = elapsed > s.staleThresholdMs
      if (shouldStale !== s.stale) {
        set({ stale: shouldStale })
      }
    },

    _reset: () => {
      // 取消正在进行的 connect：先递增 generation 让进行中的 await 早返回
      const nextGen = (get().connectGeneration ?? 0) + 1
      if (ws) {
        ws.stop()
        ws = null
      }
      stopStaleCheck()
      set({
        apiHost: DEFAULT_API_HOST,
        apiPort: DEFAULT_API_PORT,
        runtimeName: null,
        connectionState: 'idle',
        apiReady: false,
        cycleTime: 0.5,
        latestSnapshot: null,
        rawSnapshot: null,
        latestFrame: null,
        tagCatalog: [],
        snapshotReceivedAt: null,
        lastHeartbeatAt: null,
        stale: false,
        staleThresholdMs: computeStaleThresholdMs(0.5),
        lastError: null,
        connectGeneration: 0,
        previousRunSeries: [],
        writeEvents: [],
        quality: null,
        seriesVisibility: {
          'tank_2.level': true,
          'pid2.SV': true,
          'pid2.MV': true,
          'valve_1.current_opening': true,
        },
      })
      get().trendBuffer.clear()
      // generation 已归零，但同步保留 nextGen 让任何 in-flight connect 看到不一致
      if (nextGen !== 0) {
        set({ connectGeneration: nextGen })
      }
    },
  }
})
