/**
 * Stage 4 reviewer acceptance: useRuntimeStore connect/stale/generation contract.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../../src/features/runtime/useRuntimeStore'
import { computeStaleThresholdMs } from '../../src/features/runtime/dataSelection'

describe('stage 4 runtime store acceptance', () => {
  beforeEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('connect reads runtimeName from /api/status before opening WebSocket', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'acceptance_runtime',
            mode: 'REALTIME',
            cycle_count: 1,
            sim_time: 0.5,
            cycle_time: 0.5,
            safe_state: false,
            consecutive_failures: 0,
          }),
        })
      }
      if (url.includes('/meta')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ instance_name: 'acceptance_runtime', meta: {}, statistics: {} }),
        })
      }
      if (url.includes('/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            cycle_count: 1,
            sim_time: 0.5,
            'valve_1.current_opening': 40,
            'tank_2.level': 0.7,
          }),
        })
      }
      return Promise.reject(new Error(`unexpected url: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    await useRuntimeStore.getState().connect()

    expect(useRuntimeStore.getState().runtimeName).toBe('acceptance_runtime')
    expect(useRuntimeStore.getState().runtimeName).not.toBe('pid2')
    const urls = fetchMock.mock.calls.map((c) => c[0] as string)
    expect(urls[0]).toContain('/api/status')
    expect(urls.some((u) => u.includes('/instances/acceptance_runtime/snapshot'))).toBe(true)
  })

  it('heartbeat must not replace latestSnapshot', () => {
    const receivedAt = Date.now()
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 5,
        simTime: 2.5,
        sourceFlow: 0.001,
        valve: { currentOpening: 33 },
        tank1: {},
        tank2: { level: 0.6 },
        pid: {},
        _receivedAt: receivedAt,
      },
      snapshotReceivedAt: receivedAt,
      lastHeartbeatAt: null,
    })

    const before = useRuntimeStore.getState().latestSnapshot
    useRuntimeStore.setState({ lastHeartbeatAt: Date.now() })
    const after = useRuntimeStore.getState().latestSnapshot

    expect(after).toBe(before)
    expect(after?.valve.currentOpening).toBe(33)
  })

  it('stale threshold uses max(3 × cycleTime, 2s)', () => {
    useRuntimeStore.getState().setEndpoint('127.0.0.1', 8000)
    useRuntimeStore.setState({ cycleTime: 0.5 })
    expect(useRuntimeStore.getState().staleThresholdMs).toBe(computeStaleThresholdMs(0.5))
    expect(useRuntimeStore.getState().staleThresholdMs).toBeGreaterThanOrEqual(2000)
  })

  it('tickStaleCheck marks stale but keeps last snapshot values', () => {
    const old = Date.now() - 10_000
    useRuntimeStore.setState({
      latestSnapshot: {
        cycleCount: 2,
        simTime: 1,
        valve: { currentOpening: 21 },
        tank1: {},
        tank2: {},
        pid: {},
        _receivedAt: old,
      },
      snapshotReceivedAt: old,
      staleThresholdMs: 2000,
      stale: false,
    })

    useRuntimeStore.getState().tickStaleCheck()
    const s = useRuntimeStore.getState()
    expect(s.stale).toBe(true)
    expect(s.latestSnapshot?.valve.currentOpening).toBe(21)
  })

  it('disconnect increments generation so late connect cannot write state', async () => {
    let resolveStatus!: () => void
    const statusPromise = new Promise<Response>((resolve) => {
      resolveStatus = () =>
        resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'late_runtime',
            mode: 'REALTIME',
            cycle_count: 0,
            sim_time: 0,
            cycle_time: 0.5,
            safe_state: false,
            consecutive_failures: 0,
          }),
        } as Response)
    })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.endsWith('/api/status')) {
          return statusPromise
        }
        return Promise.reject(new Error('should not reach meta/snapshot after disconnect'))
      }),
    )

    const connectPromise = useRuntimeStore.getState().connect()
    const genBefore = useRuntimeStore.getState().connectGeneration
    useRuntimeStore.getState().disconnect()
    expect(useRuntimeStore.getState().connectGeneration).toBeGreaterThan(genBefore)

    resolveStatus()
    await connectPromise

    expect(useRuntimeStore.getState().runtimeName).toBeNull()
    expect(useRuntimeStore.getState().connectionState).toBe('idle')
  })
})
