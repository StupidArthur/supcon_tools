import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getMeta,
  getSnapshot,
  getStatus,
  mapApiSnapshot,
  RuntimeApiError,
} from './runtimeApi'

describe('runtimeApi.getStatus', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches /api/status and returns instance_name', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        instance_name: 'second_order_tank',
        mode: 'GENERATOR',
        cycle_count: 12,
        sim_time: 6.0,
        cycle_time: 0.5,
        safe_state: false,
        consecutive_failures: 0,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const status = await getStatus({ apiHost: '127.0.0.1', apiPort: 8000 })

    expect(status.instance_name).toBe('second_order_tank')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/status',
      expect.objectContaining({}),
    )
    expect(status.cycle_time).toBe(0.5)
  })

  it('propagates HTTP errors as RuntimeApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }),
    )
    await expect(getStatus({ apiHost: '127.0.0.1', apiPort: 8000 })).rejects.toBeInstanceOf(
      RuntimeApiError,
    )
  })
})

describe('runtimeApi.getMeta', () => {
  it('uses runtimeName from status (must not be hardcoded)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        instance_name: 'tank_A',
        meta: {},
        statistics: {},
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    // 关键：runtimeName 必须等于 /api/status.instance_name，不能与 pid2 混淆。
    const runtimeName = 'tank_A'
    await getMeta({ apiHost: '127.0.0.1', apiPort: 8000 }, runtimeName)
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/instances/${runtimeName}/meta`,
      expect.objectContaining({}),
    )
  })
})

describe('runtimeApi.getSnapshot', () => {
  it('uses runtimeName from status (must not be hardcoded)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ valve_1: { current_opening: 12 } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const runtimeName = 'second_order_tank'
    await getSnapshot({ apiHost: '127.0.0.1', apiPort: 8000 }, runtimeName)
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/instances/${runtimeName}/snapshot`,
      expect.objectContaining({}),
    )
  })

  it('encodes special characters in runtimeName', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    await getSnapshot({ apiHost: '127.0.0.1', apiPort: 8000 }, 'tank A')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/instances/tank%20A/snapshot',
      expect.objectContaining({}),
    )
  })
})

describe('runtimeApi.mapApiSnapshot', () => {
  it('maps required snake_case keys to camelCase RuntimeSnapshot', () => {
    const raw = {
      cycle_count: 5,
      sim_time: 2.5,
      source_flow: 0.0012,
      'valve_1.target_opening': 70,
      'valve_1.current_opening': 65,
      'valve_1.inlet_flow': 0.001,
      'valve_1.outlet_flow': 0.0005,
      'tank_1.level': 0.5,
      'tank_1.inlet_flow': 0.0005,
      'tank_1.outlet_flow': 0.0003,
      'tank_2.level': 0.8,
      'tank_2.inlet_flow': 0.0003,
      'tank_2.outlet_flow': 0.0002,
      'pid2.PV': 0.8,
      'pid2.SV': 0.8,
      'pid2.CSV': 0,
      'pid2.MV': 65,
      'pid2.PB': 30,
      'pid2.TI': 90,
      'pid2.TD': 20,
      'pid2.KD': 10,
      'pid2.MODE': 5,
      'pid2.SWPN': 1,
    }
    const snap = mapApiSnapshot(raw, Date.now())
    expect(snap.cycleCount).toBe(5)
    expect(snap.simTime).toBe(2.5)
    expect(snap.valve.currentOpening).toBe(65)
    expect(snap.tank2.level).toBe(0.8)
    expect(snap.pid.SV).toBe(0.8)
    expect(snap.pid.MODE).toBe(5)
  })

  it('keeps undefined for missing fields (no fake 0 / NaN substitution)', () => {
    const raw = { cycle_count: 1 }
    const snap = mapApiSnapshot(raw, Date.now())
    // 缺失字段保持 undefined（由 selectRuntimeNumber 视为 null）
    expect(snap.valve.currentOpening).toBeUndefined()
    expect(snap.tank2.level).toBeUndefined()
    expect(snap.pid.SV).toBeUndefined()
  })

  it('treats non-finite numbers as undefined', () => {
    const raw = {
      'valve_1.current_opening': 'not-a-number',
      'tank_2.level': NaN,
    }
    const snap = mapApiSnapshot(raw, Date.now())
    expect(snap.valve.currentOpening).toBeUndefined()
    // NaN is not finite → undefined
    expect(snap.tank2.level).toBeUndefined()
  })

  it('MISSING cycle_count/sim_time MUST stay undefined (NOT mapped to fake 0)', () => {
    // 契约：snapshot 缺 cycle_count/sim_time 时必须保留 undefined；
    // 映射为 0 会与"Engine 未启动 cycle=0"或"启动后尚未推周期"混淆。
    const raw = {
      'valve_1.current_opening': 12.5,
      'tank_2.level': 0.8,
      // 故意没有 cycle_count 和 sim_time
    }
    const snap = mapApiSnapshot(raw, Date.now())
    expect(snap.cycleCount).toBeUndefined()
    expect(snap.simTime).toBeUndefined()
    // 其它字段正常
    expect(snap.valve.currentOpening).toBe(12.5)
    expect(snap.tank2.level).toBe(0.8)
  })

  it('NON-FINITE cycle_count/sim_time must stay undefined (NOT mapped to NaN/Infinity)', () => {
    const raw = {
      cycle_count: 'NaN-value',
      sim_time: Infinity,
      'valve_1.current_opening': 12,
    }
    const snap = mapApiSnapshot(raw, Date.now())
    expect(snap.cycleCount).toBeUndefined()
    expect(snap.simTime).toBeUndefined()
    expect(snap.valve.currentOpening).toBe(12)
  })

  it('valid cycle_count/sim_time are preserved', () => {
    const raw = { cycle_count: 42, sim_time: 21.5 }
    const snap = mapApiSnapshot(raw, Date.now())
    expect(snap.cycleCount).toBe(42)
    expect(snap.simTime).toBe(21.5)
  })
})