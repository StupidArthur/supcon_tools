// useRuntimeStore.connect/disconnect race 测试
//
// 真实场景：用户在 RuntimeToolbar 点"启动仿真"时调用 runtimeConnect()，
// 它开始 await getStatus(...)。await 期间用户点"停止"或离开页面，
// runtimeDisconnect() 被调用。
//
// 关键契约：
//   - disconnect 必须在 disconnect 调用瞬间关闭 WS / 定时器，并标记 stale。
//   - 即使 disconnect 后 connect 的 await 仍然回来，也不应再创建 WS 或写入
//     latestSnapshot / connectionState。
//   - useRuntimeStore 用 generation token 跟踪每次 connect 调用。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from './useRuntimeStore'

// FakeWebSocket 用于在 jsdom 中模拟 WS
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3

  url: string
  readyState: number = 0
  onopen: ((ev: any) => void) | null = null
  onmessage: ((ev: any) => void) | null = null
  onerror: ((ev: any) => void) | null = null
  onclose: ((ev: any) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  close(): void {
    this.readyState = FakeWebSocket.CLOSED
    if (this.onclose) this.onclose({})
  }
  triggerOpen(): void {
    this.readyState = FakeWebSocket.OPEN
    if (this.onopen) this.onopen({})
  }
}

describe('useRuntimeStore - connect/disconnect race', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as any)
  })

  afterEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('disconnect during async getStatus MUST prevent WS creation', async () => {
    let resolveStatus: (v: any) => void = () => {}
    const statusPromise = new Promise<any>((resolve) => { resolveStatus = resolve })
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) return statusPromise
      return Promise.reject(new Error('unexpected url: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)

    const connectPromise = useRuntimeStore.getState().connect()
    // 此时 connect() 正在 await getStatus；disconnect 必须能立即生效
    useRuntimeStore.getState().disconnect()
    // 即使 status 之后才返回
    resolveStatus({
      instance_name: 'real_runtime',
      mode: 'GENERATOR',
      cycle_count: 0,
      sim_time: 0,
      cycle_time: 0.5,
      safe_state: false,
      consecutive_failures: 0,
    })
    await connectPromise

    // 关键：connect() 因 generation 失效，应放弃创建 WS
    expect(FakeWebSocket.instances.length).toBe(0)
    expect(useRuntimeStore.getState().connectionState).toBe('idle')
    expect(useRuntimeStore.getState().runtimeName).toBeNull()
  })

  it('connect → disconnect → connect AGAIN → only latest WS exists', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'real_runtime',
            mode: 'GENERATOR',
            cycle_count: 0,
            sim_time: 0,
            cycle_time: 0.5,
            safe_state: false,
            consecutive_failures: 0,
          }),
        })
      }
      if (url.endsWith('/meta')) {
        return Promise.resolve({
          ok: true, status: 200, json: async () => ({ meta: {}, statistics: {} }),
        })
      }
      if (url.endsWith('/snapshot')) {
        return Promise.resolve({
          ok: true, status: 200, json: async () => ({ cycle_count: 1, sim_time: 0.5 }),
        })
      }
      return Promise.reject(new Error('unexpected url: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)

    // 第一次 connect
    await useRuntimeStore.getState().connect()
    expect(FakeWebSocket.instances.length).toBe(1)
    FakeWebSocket.instances[0].triggerOpen()
    expect(useRuntimeStore.getState().connectionState).toBe('connected')

    // disconnect
    useRuntimeStore.getState().disconnect()
    expect(useRuntimeStore.getState().connectionState).toBe('idle')
    expect(FakeWebSocket.instances[0].readyState).toBe(FakeWebSocket.CLOSED)

    // 第二次 connect（重新连）
    await useRuntimeStore.getState().connect()
    expect(FakeWebSocket.instances.length).toBe(2)
    FakeWebSocket.instances[1].triggerOpen()
    expect(useRuntimeStore.getState().connectionState).toBe('connected')
  })

  it('disconnect freezes latestSnapshot and marks stale', () => {
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 5,
        simTime: 2.5,
        sourceFlow: 0.0012,
        valve: { targetOpening: 80, currentOpening: 65, inletFlow: 0.001, outletFlow: 0.0005 },
        tank1: { level: 0.4, inletFlow: 0.0005, outletFlow: 0.0003 },
        tank2: { level: 0.6, inletFlow: 0.0003, outletFlow: 0.0002 },
        pid: { PV: 0.6, SV: 0.8, CSV: 0, MV: 65, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 },
        _receivedAt: Date.now(),
      },
      snapshotReceivedAt: Date.now() - 10_000, // 已超过 stale 阈值
      stale: false,
      connectionState: 'connected',
    })
    useRuntimeStore.getState().disconnect()
    const s = useRuntimeStore.getState()
    // latestSnapshot 必须保留（冻结最后值）
    expect(s.latestSnapshot).not.toBeNull()
    expect(s.latestSnapshot?.cycleCount).toBe(5)
    expect(s.snapshotReceivedAt).not.toBeNull()
    expect(s.connectionState).toBe('idle')
    // stale 必须为 true（disconnect 后视为断线）
    expect(s.stale).toBe(true)
  })

  it('disconnect within stale threshold still marks stale (契约：断线即 stale)', () => {
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 1,
        simTime: 0.5,
        sourceFlow: 0.0012,
        valve: {}, tank1: {}, tank2: {}, pid: {},
        _receivedAt: Date.now(),
      },
      snapshotReceivedAt: Date.now(), // 刚刚
      stale: false,
      connectionState: 'connected',
    })
    useRuntimeStore.getState().disconnect()
    // 即使时间未超阈值，断线也必须设置 stale=true（按契约）
    expect(useRuntimeStore.getState().stale).toBe(true)
  })

  it('connect pending during disconnect does NOT update connectionState to connecting', async () => {
    let resolveStatus: (v: any) => void = () => {}
    const statusPromise = new Promise<any>((resolve) => { resolveStatus = resolve })
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) return statusPromise
      return Promise.reject(new Error('unexpected'))
    })
    vi.stubGlobal('fetch', fetchMock)

    const connectPromise = useRuntimeStore.getState().connect()
    // 不应立即创建 WS
    expect(FakeWebSocket.instances.length).toBe(0)
    // disconnect 在 status 还没回来时触发
    useRuntimeStore.getState().disconnect()
    expect(useRuntimeStore.getState().connectionState).toBe('idle')
    expect(useRuntimeStore.getState().stale).toBe(true)
    // 现在 status 回来
    resolveStatus({
      instance_name: 'real_runtime',
      mode: 'GENERATOR',
      cycle_count: 0, sim_time: 0, cycle_time: 0.5,
      safe_state: false, consecutive_failures: 0,
    })
    await connectPromise
    // generation 失效，不应再创建 WS
    expect(FakeWebSocket.instances.length).toBe(0)
    // runtimeName 必须保持 null（disconnect 已"取消"该次 connect）
    expect(useRuntimeStore.getState().runtimeName).toBeNull()
  })

  it('connect generation increments on each call (cancel previous connect)', async () => {
    const gen0 = useRuntimeStore.getState().connectGeneration
    // 第一次 connect（卡在 fetch）
    let resolveStatus: (v: any) => void = () => {}
    const statusPromise = new Promise<any>((resolve) => { resolveStatus = resolve })
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) return statusPromise
      if (url.endsWith('/meta')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ meta: {}, statistics: {} }),
        })
      }
      if (url.endsWith('/snapshot')) {
        return Promise.resolve({
          ok: true, status: 200, json: async () => ({ cycle_count: 1, sim_time: 0.5 }),
        })
      }
      return Promise.reject(new Error('unexpected'))
    })
    vi.stubGlobal('fetch', fetchMock)

    const c1 = useRuntimeStore.getState().connect()
    const gen1 = useRuntimeStore.getState().connectGeneration
    expect(gen1).toBeGreaterThan(gen0)
    // 第二次 connect
    const c2 = useRuntimeStore.getState().connect()
    const gen2 = useRuntimeStore.getState().connectGeneration
    expect(gen2).toBeGreaterThan(gen1)
    // 让两个 promise 完成
    resolveStatus({
      ok: true,
      status: 200,
      json: async () => ({
        instance_name: 'real', mode: 'GENERATOR', cycle_count: 0, sim_time: 0,
        cycle_time: 0.5, safe_state: false, consecutive_failures: 0,
      }),
    })
    await Promise.all([c1, c2])
    // 只有第二次的 connect 应实际创建 WS（最新 generation）
    expect(useRuntimeStore.getState().connectionState).not.toBe('idle')
    expect(useRuntimeStore.getState().runtimeName).toBe('real')
  })

  it('disconnect during deferred initial snapshot freezes state and prevents late WS creation', async () => {
    let resolveSnapshot!: (response: any) => void
    const snapshotFetch = new Promise<any>((resolve) => { resolveSnapshot = resolve })
    const oldSnapshot = {
      cycleCount: 9,
      simTime: 4.5,
      valve: {}, tank1: {}, tank2: {}, pid: {},
      _receivedAt: 100,
    }
    useRuntimeStore.setState({
      latestSnapshot: oldSnapshot,
      snapshotReceivedAt: 100,
      stale: false,
    })
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true, status: 200, json: async () => ({
            instance_name: 'real_runtime', mode: 'GENERATOR', cycle_count: 10,
            sim_time: 5, cycle_time: 0.5, safe_state: false, consecutive_failures: 0,
          }),
        })
      }
      if (url.endsWith('/meta')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ meta: {} }) })
      }
      if (url.endsWith('/snapshot')) return snapshotFetch
      return Promise.reject(new Error(`unexpected ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    const connecting = useRuntimeStore.getState().connect()
    // Let status and meta finish so connect is blocked specifically inside snapshot GET.
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith('/snapshot'))).toBe(true)
    })
    const snapshotCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith('/snapshot'))
    const signal = snapshotCall?.[1]?.signal as AbortSignal

    useRuntimeStore.getState().disconnect()
    expect(signal.aborted).toBe(true)
    resolveSnapshot({
      ok: true, status: 200, json: async () => ({ cycle_count: 99, sim_time: 49.5 }),
    })
    await connecting

    const final = useRuntimeStore.getState()
    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(final.latestSnapshot).toBe(oldSnapshot)
    expect(final.snapshotReceivedAt).toBe(100)
    expect(final.stale).toBe(true)
    expect(final.connectionState).toBe('idle')
  })

  it('empty REST snapshot does not replace or freshen the last real snapshot', async () => {
    const oldSnapshot = {
      cycleCount: 9,
      simTime: 4.5,
      valve: {}, tank1: {}, tank2: {}, pid: {},
      _receivedAt: 100,
    }
    useRuntimeStore.setState({
      latestSnapshot: oldSnapshot,
      snapshotReceivedAt: 100,
      stale: true,
    })
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) return Promise.resolve({
        ok: true, status: 200, json: async () => ({
          instance_name: 'real_runtime', mode: 'GENERATOR', cycle_count: 0,
          sim_time: 0, cycle_time: 0.5, safe_state: false, consecutive_failures: 0,
        }),
      })
      if (url.endsWith('/meta')) return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      if (url.endsWith('/snapshot')) return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      return Promise.reject(new Error(`unexpected ${url}`))
    }))

    await useRuntimeStore.getState().connect()
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(useRuntimeStore.getState().latestSnapshot).toBe(oldSnapshot)
    expect(useRuntimeStore.getState().snapshotReceivedAt).toBe(100)
    expect(useRuntimeStore.getState().stale).toBe(true)
  })
})
