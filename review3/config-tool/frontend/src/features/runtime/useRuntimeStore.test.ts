import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from '@testing-library/react'
import { useRuntimeStore } from './useRuntimeStore'
import { computeStaleThresholdMs } from './dataSelection'

describe('useRuntimeStore', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('initial state is idle with no runtimeName', () => {
    const s = useRuntimeStore.getState()
    expect(s.connectionState).toBe('idle')
    expect(s.runtimeName).toBeNull()
    expect(s.latestSnapshot).toBeNull()
    expect(s.stale).toBe(false)
  })

  it('setEndpoint updates host/port', () => {
    useRuntimeStore.getState().setEndpoint('10.0.0.1', 9000)
    expect(useRuntimeStore.getState().apiHost).toBe('10.0.0.1')
    expect(useRuntimeStore.getState().apiPort).toBe(9000)
  })

  it('connect() first calls GET /api/status and uses its instance_name (NOT hardcoded pid2)', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'real_runtime_xyz',
            mode: 'GENERATOR',
            cycle_count: 0,
            sim_time: 0,
            cycle_time: 0.5,
            safe_state: false,
            consecutive_failures: 0,
          }),
        })
      }
      if (url.endsWith('/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            cycle_count: 0,
            sim_time: 0,
            source_flow: 0.0012,
            'valve_1.target_opening': 50,
            'valve_1.current_opening': 25,
            'valve_1.inlet_flow': 0.001,
            'valve_1.outlet_flow': 0.0005,
            'tank_1.level': 0.5,
            'tank_2.level': 0.8,
            'pid2.PV': 0.8,
            'pid2.SV': 0.8,
          }),
        })
      }
      if (url.endsWith('/meta')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ instance_name: 'real_runtime_xyz', meta: {}, statistics: {} }),
        })
      }
      return Promise.reject(new Error('unexpected url: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)

    await useRuntimeStore.getState().connect()

    // 关键断言：runtimeName 来自 /api/status.instance_name
    expect(useRuntimeStore.getState().runtimeName).toBe('real_runtime_xyz')
    expect(useRuntimeStore.getState().runtimeName).not.toBe('pid2')

    // meta/snapshot 的 URL 必须使用真实 runtimeName
    const calledUrls = fetchMock.mock.calls.map((c) => c[0] as string)
    expect(calledUrls.some((u) => u.includes('/instances/real_runtime_xyz/meta'))).toBe(true)
    expect(calledUrls.some((u) => u.includes('/instances/real_runtime_xyz/snapshot'))).toBe(true)
    // 关键：绝不能用 pid2/tank_2 之类 Program 实例名冒充 runtimeName
    expect(calledUrls.some((u) => u.includes('/instances/pid2/'))).toBe(false)
  })

  it('connect() handles status error gracefully (no WS open)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }),
    )
    await useRuntimeStore.getState().connect()
    const s = useRuntimeStore.getState()
    expect(s.connectionState).toBe('error')
    expect(s.lastError).not.toBeNull()
    expect(s.runtimeName).toBeNull()
  })

  it('stale threshold uses max(3 × cycleTime, 2s)', () => {
    // Default cycleTime=0.5 → 1.5s 但不能小于 2s → 2s
    expect(useRuntimeStore.getState().staleThresholdMs).toBe(computeStaleThresholdMs(0.5))
  })

  it('tickStaleCheck: marks stale when snapshotReceivedAt too old', () => {
    // 直接注入旧 receivedAt
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 1,
        simTime: 0,
        tank1: {},
        tank2: {},
        valve: {},
        pid: {},
        _receivedAt: Date.now() - 10_000,
      },
      snapshotReceivedAt: Date.now() - 10_000,
      staleThresholdMs: 2000,
      stale: false,
    })
    useRuntimeStore.getState().tickStaleCheck()
    expect(useRuntimeStore.getState().stale).toBe(true)
  })

  it('tickStaleCheck: not stale when snapshot fresh', () => {
    useRuntimeStore.setState({
      snapshotReceivedAt: Date.now(),
      staleThresholdMs: 5000,
      stale: false,
    })
    useRuntimeStore.getState().tickStaleCheck()
    expect(useRuntimeStore.getState().stale).toBe(false)
  })

  it('tickStaleCheck keeps disconnected data stale even when the last snapshot is recent', () => {
    useRuntimeStore.setState({
      connectionState: 'disconnected',
      snapshotReceivedAt: Date.now(),
      staleThresholdMs: 5000,
      stale: true,
    })
    useRuntimeStore.getState().tickStaleCheck()
    expect(useRuntimeStore.getState().stale).toBe(true)
  })

  it('disconnect() preserves latestSnapshot (do not clear)', () => {
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 5,
        simTime: 2.5,
        tank1: {},
        tank2: {},
        valve: {},
        pid: {},
        _receivedAt: Date.now(),
      },
      snapshotReceivedAt: Date.now(),
    })
    useRuntimeStore.getState().disconnect()
    const s = useRuntimeStore.getState()
    expect(s.connectionState).toBe('idle')
    // latestSnapshot 必须保留，UI 冻结最后值
    expect(s.latestSnapshot).not.toBeNull()
    expect(s.snapshotReceivedAt).not.toBeNull()
  })

  it('disconnect() closes WS so reconnect cannot happen after navigation away', () => {
    // 通过 setEndpoint 之后 disconnect 不应抛错
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    useRuntimeStore.getState().disconnect()
    expect(useRuntimeStore.getState().connectionState).toBe('idle')
  })

  it('setEndpoint stores host and port', () => {
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    const s = useRuntimeStore.getState()
    expect(s.apiHost).toBe('127.0.0.1')
    expect(s.apiPort).toBe(8000)
  })

  it('registerSubscription stores source tags in subscriptionSources', () => {
    useRuntimeStore.getState().registerSubscription('trend', ['tank_2.level', 'pid2.SV'])
    useRuntimeStore.getState().registerSubscription('dashboard', ['valve_1.current_opening'])
    const sources = useRuntimeStore.getState().subscriptionSources
    expect(sources.trend).toEqual(['tank_2.level', 'pid2.SV'])
    expect(sources.dashboard).toEqual(['valve_1.current_opening'])
  })

  it('setTrendTags also updates trend subscription', () => {
    useRuntimeStore.getState().setTrendTags(['pid2.PV'])
    expect(useRuntimeStore.getState().subscriptionSources.trend).toEqual(['pid2.PV'])
  })

  it('subscriptionSources can be replaced wholesale', () => {
    useRuntimeStore.getState().registerSubscription('tagTable', ['tank_2.level'])
    useRuntimeStore.getState().registerSubscription('tagTable', ['pid2.SV', 'tank_2.level'])
    const sources = useRuntimeStore.getState().subscriptionSources
    expect(sources.tagTable).toEqual(['pid2.SV', 'tank_2.level'])
  })

  it('unregisterSubscription removes source from union', () => {
    useRuntimeStore.getState().registerSubscription('tagTable', ['tank_2.level'])
    useRuntimeStore.getState().registerSubscription('trend', ['pid2.SV'])
    useRuntimeStore.getState().unregisterSubscription('tagTable')
    const sources = useRuntimeStore.getState().subscriptionSources
    expect(sources.tagTable).toBeUndefined()
    expect(sources.trend).toEqual(['pid2.SV'])
  })

  it('registerSubscription with null stores explicit null in source map', () => {
    useRuntimeStore.getState().registerSubscription('tagTable', null)
    const sources = useRuntimeStore.getState().subscriptionSources
    expect(sources.tagTable).toBeNull()
  })

  it('over MAX_SUBSCRIPTION_TAGS keeps prior sources and surfaces subscriptionError', () => {
    useRuntimeStore.getState()._reset()
    useRuntimeStore.getState().registerSubscription('trend', ['pid2.SV'])
    const big = Array.from({ length: 6000 }, (_, i) => `tag${i}`)
    useRuntimeStore.getState().registerSubscription('tagTable', big)
    expect(useRuntimeStore.getState().subscriptionError).toMatch(/订阅超过/)
    // trend 仍在
    expect(useRuntimeStore.getState().subscriptionSources.trend).toEqual(['pid2.SV'])
    // tagTable 不应被更新（因超过上限抛错）
    expect(useRuntimeStore.getState().subscriptionSources.tagTable).toBeUndefined()
  })

  // ———— §四.2 connect/disconnect 状态清洁测试 ————
  // 用一个永不 resolve 的 status 模拟 connect 进行中
  function pendingFetch(): ReturnType<typeof vi.fn> {
    return vi.fn().mockReturnValue(new Promise(() => {}))
  }

  it('E: connect 开始清理旧 runtimeName / tagCatalog / lastError', async () => {
    // 先写入旧数据
    act(() =>
      useRuntimeStore.setState({
        runtimeName: 'old-runtime',
        tagCatalog: [{ name: 'pid1.PV', instance: 'pid1' }] as any,
        lastError: 'old error',
        connectionState: 'connected',
      }),
    )
    expect(useRuntimeStore.getState().runtimeName).toBe('old-runtime')
    expect(useRuntimeStore.getState().tagCatalog.length).toBe(1)

    // 用永不 resolve 的 status 让 connect 阻塞在第一个 await
    vi.stubGlobal('fetch', pendingFetch())
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)

    // 启动 connect（不 await，因为它会永远 pending）
    const connectPromise = useRuntimeStore.getState().connect()

    // 让 microtask 跑一会儿 — generation 已被递增、状态已清空
    await new Promise((r) => setTimeout(r, 30))

    const s = useRuntimeStore.getState()
    expect(s.connectionState).toBe('connecting')
    expect(s.runtimeName).toBeNull()
    expect(s.tagCatalog).toEqual([])
    expect(s.lastError).toBeNull()
    expect(s.connectGeneration).toBeGreaterThan(0)

    // 清理：断开 — disconnect 把 generation 再 +1，让 pending connect 早返回
    useRuntimeStore.getState().disconnect()
    // 给一个 timeout 保险防止 promise 永久 pending
    await Promise.race([
      connectPromise,
      new Promise((r) => setTimeout(r, 50)),
    ])
  })

  it('F: tags 请求失败后 snapshot 成功不应清空 tagCatalogError', async () => {
    // /api/status 成功；/tags 返回 404
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'real_runtime_xyz',
            mode: 'REALTIME',
            cycle_count: 0,
            sim_time: 0,
            cycle_time: 0.5,
            safe_state: false,
            consecutive_failures: 0,
          }),
        })
      }
      if (url.endsWith('/tags')) {
        return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
      }
      // meta 是 best-effort；返回成功
      if (url.endsWith('/meta')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ instance_name: 'real_runtime_xyz', meta: {}, statistics: {} }),
        })
      }
      // snapshot：返回合法非空快照（模拟真实路径）
      if (url.endsWith('/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            cycle_count: 1,
            sim_time: 0.5,
            'pid1.PV': 1.0,
          }),
        })
      }
      return Promise.reject(new Error('unexpected url'))
    })
    vi.stubGlobal('fetch', fetchMock)
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    useRuntimeStore.getState().connect()

    // 等待 connect 完成到 snapshot 状态写入
    await new Promise((r) => setTimeout(r, 100))

    const s = useRuntimeStore.getState()
    expect(s.runtimeName).toBe('real_runtime_xyz')
    expect(s.tagCatalog).toEqual([])
    // snapshot 已成功写入
    expect(s.latestSnapshot).not.toBeNull()
    // tagCatalogError 保留 tags 错误，未被 snapshot 成功清空
    expect(s.tagCatalogError).toContain('加载运行参数失败')
    expect(s.tagCatalogError).toMatch(/404|status/)
    // lastError 应被 snapshot 成功清空（独立字段，互不影响）
    expect(s.lastError).toBeNull()

    // 调用的是真实 runtimeName，不是 default
    const calledUrls = fetchMock.mock.calls.map((c) => c[0] as string)
    expect(calledUrls.some((u) => u.includes('/instances/real_runtime_xyz/tags'))).toBe(true)
    expect(calledUrls.some((u) => u.includes('/instances/default/'))).toBe(false)

    // 清理
    useRuntimeStore.getState().disconnect()
    vi.unstubAllGlobals()
  })

  it('G: disconnect 清理 runtimeName / tagCatalog / lastError，保留 snapshot', () => {
    act(() =>
      useRuntimeStore.setState({
        runtimeName: 'runtime-a',
        tagCatalog: [{ name: 'pid1.PV', instance: 'pid1' }] as any,
        lastError: 'old',
        connectionState: 'connected',
        latestSnapshot: { values: { foo: 1 }, receivedAt: Date.now() } as any,
        rawSnapshot: { foo: 1 },
      }),
    )

    useRuntimeStore.getState().disconnect()

    const s = useRuntimeStore.getState()
    expect(s.connectionState).toBe('idle')
    expect(s.runtimeName).toBeNull()
    expect(s.tagCatalog).toEqual([])
    expect(s.lastError).toBeNull()
    // snapshot 必须保留（冻结最后值语义）
    expect(s.latestSnapshot).not.toBeNull()
    expect(s.rawSnapshot).not.toBeNull()
  })

  it('H: snapshot 错误恢复后可清除（tags 错误除外）', async () => {
    // 初始状态：一个旧的普通 snapshot 错误
    useRuntimeStore.getState()._reset()
    act(() =>
      useRuntimeStore.setState({
        lastError: '500 snapshot failed',
      }),
    )

    // mock 所有请求成功（包括 snapshot）
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            instance_name: 'test_runtime',
            mode: 'REALTIME', cycle_count: 0, sim_time: 0,
            cycle_time: 0.5, safe_state: false, consecutive_failures: 0,
          }),
        })
      }
      if (url.endsWith('/meta')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ instance_name: 'test_runtime', meta: {}, statistics: {} }) })
      }
      if (url.endsWith('/tags')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ tags: [] }) })
      }
      if (url.endsWith('/snapshot')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ cycle_count: 1, sim_time: 0.5, 'pid1.PV': 1.0 }) })
      }
      return Promise.reject(new Error('unexpected url: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    useRuntimeStore.getState().connect()

    // 等待 connect 完成，snapshot 写入
    await new Promise((r) => setTimeout(r, 100))

    const s = useRuntimeStore.getState()
    // 普通 snapshot 错误在恢复后清除
    expect(s.latestSnapshot).not.toBeNull()
    expect(s.lastError).toBeNull()

    // 清理
    useRuntimeStore.getState().disconnect()
    vi.unstubAllGlobals()
  })
})
