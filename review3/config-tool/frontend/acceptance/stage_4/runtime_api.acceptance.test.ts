/**
 * Stage 4 reviewer acceptance: runtimeApi REST contract.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getMeta,
  getSnapshot,
  getStatus,
  mapApiSnapshot,
  RuntimeApiError,
} from '../../src/features/runtime/runtimeApi'

describe('stage 4 runtime api acceptance', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('runtimeName must come from /api/status.instance_name', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          instance_name: 'second_order_tank',
          mode: 'REALTIME',
          cycle_count: 3,
          sim_time: 1.5,
          cycle_time: 0.5,
          safe_state: false,
          consecutive_failures: 0,
        }),
      }),
    )

    const status = await getStatus({ apiHost: '127.0.0.1', apiPort: 8000 })
    expect(status.instance_name).toBe('second_order_tank')
    expect(status.instance_name).not.toBe('pid2')
  })

  it('meta and snapshot URLs must use runtimeName from status', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            instance_name: 'runtime_from_status',
            mode: 'REALTIME',
            cycle_count: 0,
            sim_time: 0,
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
          json: async () => ({ instance_name: 'runtime_from_status', meta: {}, statistics: {} }),
        })
      }
      if (url.includes('/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ cycle_count: 1, sim_time: 0.5 }),
        })
      }
      return Promise.reject(new Error(`unexpected url: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    const status = await getStatus({ apiHost: '127.0.0.1', apiPort: 8000 })
    await getMeta({ apiHost: '127.0.0.1', apiPort: 8000 }, status.instance_name)
    await getSnapshot({ apiHost: '127.0.0.1', apiPort: 8000 }, status.instance_name)

    const urls = fetchMock.mock.calls.map((c) => c[0] as string)
    expect(urls.some((u) => u.includes('/instances/runtime_from_status/meta'))).toBe(true)
    expect(urls.some((u) => u.includes('/instances/runtime_from_status/snapshot'))).toBe(true)
    expect(urls.some((u) => u.includes('/instances/pid2/'))).toBe(false)
  })

  it('mapApiSnapshot keeps missing fields undefined (never coerces to 0)', () => {
    const snap = mapApiSnapshot(
      {
        source_flow: 0.0012,
        'valve_1.current_opening': 12.5,
      },
      Date.now(),
    )
    expect(snap.cycleCount).toBeUndefined()
    expect(snap.simTime).toBeUndefined()
    expect(snap.tank2.level).toBeUndefined()
    expect(snap.valve.currentOpening).toBe(12.5)
  })

  it('mapApiSnapshot rejects non-finite numbers as undefined', () => {
    const snap = mapApiSnapshot(
      {
        cycle_count: Number.NaN,
        'valve_1.current_opening': 'not-a-number',
      },
      Date.now(),
    )
    expect(snap.cycleCount).toBeUndefined()
    expect(snap.valve.currentOpening).toBeUndefined()
  })

  it('propagates HTTP errors as RuntimeApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }),
    )
    await expect(
      getSnapshot({ apiHost: '127.0.0.1', apiPort: 8000 }, 'missing_runtime'),
    ).rejects.toBeInstanceOf(RuntimeApiError)
  })
})
