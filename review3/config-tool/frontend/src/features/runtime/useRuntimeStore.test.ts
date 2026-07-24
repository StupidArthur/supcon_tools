import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

  it('setEndpoint with token stores token in-memory', () => {
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000, 'in-memory-token')
    const s = useRuntimeStore.getState()
    expect(s.apiToken).toBe('in-memory-token')
    expect(s.apiHost).toBe('127.0.0.1')
    expect(s.apiPort).toBe(8000)
  })

  it('setEndpoint without token keeps token empty', () => {
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    expect(useRuntimeStore.getState().apiToken).toBe('')
  })

  it('connect() passes Authorization header when apiToken is set', async () => {
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000, 'in-memory-token')
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'real_runtime',
            mode: 'REALTIME',
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
          json: async () => ({ cycle_count: 0, sim_time: 0 }),
        })
      }
      if (url.endsWith('/meta')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ instance_name: 'real_runtime', meta: {}, statistics: {} }),
        })
      }
      return Promise.reject(new Error('unexpected url: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)
    await useRuntimeStore.getState().connect()

    const statusCall = fetchMock.mock.calls.find((c) => (c[0] as string).endsWith('/api/status'))
    expect(statusCall).toBeDefined()
    const headers = statusCall![1]?.headers as Record<string, string> | undefined
    expect(headers?.Authorization).toBe('Bearer in-memory-token')
  })
})
