import { describe, expect, it } from 'vitest'
import {
  computeStaleThresholdMs,
  FLOW_ANIMATION_THRESHOLD_M3S,
  formatRuntimeNumber,
  getRuntimeNumber,
  isRuntimeRunning,
  selectPIDMode,
  selectPIDSetpoint,
  selectPipeFlow,
  selectSourceFlow,
  selectTankLevel,
  selectValveOpening,
  shouldShowFlowAnimation,
} from './dataSelection'
import type { ConnectionState } from './types'
import type { DraftConfig } from '../templates/types'

const baseDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: {
    fullTravelTime: 12,
    initialOpening: 0,
    flowCoefficient: 1,
    minOpening: 0,
    maxOpening: 100,
  },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

describe('isRuntimeRunning', () => {
  it('only SIMULATION/REALTIME is running', () => {
    expect(isRuntimeRunning('SIMULATION_RUNNING')).toBe(true)
    expect(isRuntimeRunning('REALTIME_RUNNING')).toBe(true)
    expect(isRuntimeRunning('STOPPED_EDITING')).toBe(false)
    expect(isRuntimeRunning('STARTING')).toBe(false)
    expect(isRuntimeRunning('STOPPING')).toBe(false)
    expect(isRuntimeRunning('ERROR')).toBe(false)
    expect(isRuntimeRunning('BATCH_RUNNING')).toBe(false)
  })
})

describe('getRuntimeNumber', () => {
  it('returns null when running but snapshot is missing', () => {
    const r = getRuntimeNumber(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: null, draft: baseDraft },
      () => 42,
      (d) => d.pid.SV,
    )
    expect(r.value).toBeNull()
    expect(r.present).toBe(false)
  })

  it('returns null when running but field is missing in snapshot', () => {
    const r = getRuntimeNumber(
      {
        runtimeState: 'SIMULATION_RUNNING',
        latestSnapshot: { ...buildSnap({}), _receivedAt: 0 } as any,
        draft: baseDraft,
      },
      () => undefined,
      (d) => d.pid.SV,
    )
    expect(r.value).toBeNull()
    expect(r.present).toBe(false)
  })

  it('returns snapshot value when running and field exists', () => {
    const snap = buildSnap({ tank2Level: 0.42 })
    const r = getRuntimeNumber(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft, runningConfig: baseDraft },
      (s) => s.tank2.level,
      (d) => d.tank2.initialLevel,
    )
    expect(r.value).toBe(0.42)
    expect(r.present).toBe(true)
    expect(r.finite).toBe(true)
  })

  it('returns draft value when stopped (not snapshot)', () => {
    const r = getRuntimeNumber(
      { runtimeState: 'STOPPED_EDITING', latestSnapshot: null, draft: baseDraft },
      (s) => s.tank2.level,
      (d) => d.tank2.initialLevel,
    )
    expect(r.value).toBe(0.1) // draft.initialLevel
  })

  it('running state must NEVER fall back to draft (no fake live values)', () => {
    // 即使 draft 有值，运行态且 snapshot 缺失时必须返回 null。
    const r = getRuntimeNumber(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: null, draft: baseDraft },
      () => undefined,
      (d) => d.tank2.initialLevel,
    )
    expect(r.value).toBeNull()
  })
})

describe('selectTankLevel', () => {
  it('clamps ratio to [0,1] but keeps raw value for out-of-range', () => {
    const snap = buildSnap({ tank2Level: 1.5 }) // > height
    const result = selectTankLevel(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft, runningConfig: baseDraft },
      'tank2',
    )
    // raw value preserved
    expect(result.level).toBe(1.5)
    // ratio flagged as out-of-range
    expect(result.outOfRange).toBe(true)
    // height comes from the frozen running config (not the editable draft)
    expect(result.height).toBe(1.2)
    expect(result.ratio).not.toBeNull()
    expect(result.ratio!).toBeGreaterThan(1)
  })

  it('normal level returns ratio in [0,1]', () => {
    const snap = buildSnap({ tank2Level: 0.6 })
    const result = selectTankLevel(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft, runningConfig: baseDraft },
      'tank2',
    )
    expect(result.outOfRange).toBe(false)
    expect(result.ratio).toBeCloseTo(0.5, 9)
  })

  it('returns null fields when stopped without draft', () => {
    const result = selectTankLevel(
      { runtimeState: 'STOPPED_EDITING', latestSnapshot: null, draft: null },
      'tank2',
    )
    expect(result.level).toBeNull()
    expect(result.height).toBeNull()
    expect(result.ratio).toBeNull()
  })
})

describe('selectValveOpening', () => {
  it('uses current_opening (not target_opening) in running state', () => {
    const snap = buildSnap({ valveCurrentOpening: 33.5, valveTargetOpening: 80 })
    const result = selectValveOpening({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: snap,
      draft: baseDraft,
    })
    expect(result.value).toBe(33.5)
  })

  it('falls back to initial_opening when stopped', () => {
    const result = selectValveOpening({
      runtimeState: 'STOPPED_EDITING',
      latestSnapshot: null,
      draft: baseDraft,
    })
    expect(result.value).toBe(0) // valve.initialOpening
  })

  it('returns null when running but current_opening missing', () => {
    const snap = buildSnap({}) // no current_opening
    // overwrite the snap's valve fields to undefined to simulate missing
    snap.valve.currentOpening = undefined as any
    const result = selectValveOpening({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: snap,
      draft: baseDraft,
    })
    expect(result.value).toBeNull()
  })
})

describe('shouldShowFlowAnimation', () => {
  const runningCtx = { runtimeState: 'SIMULATION_RUNNING' as const, latestSnapshot: null as any, draft: baseDraft }

  it('false when not running', () => {
    const snap = buildSnap({ valveOutletFlow: 0.001 })
    expect(shouldShowFlowAnimation(
      { runtimeState: 'STOPPED_EDITING', latestSnapshot: snap, draft: baseDraft },
      'connected', false, 'inlet',
    )).toBe(false)
  })

  it('false when connection is not connected', () => {
    const snap = buildSnap({ valveOutletFlow: 0.001 })
    expect(shouldShowFlowAnimation(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'disconnected', false, 'inlet',
    )).toBe(false)
  })

  it('false when stale', () => {
    const snap = buildSnap({ valveOutletFlow: 0.001 })
    expect(shouldShowFlowAnimation(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'connected', true, 'inlet',
    )).toBe(false)
  })

  it('false when flow below threshold', () => {
    const snap = buildSnap({ valveInletFlow: FLOW_ANIMATION_THRESHOLD_M3S / 2 })
    expect(shouldShowFlowAnimation(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'connected', false, 'inlet',
    )).toBe(false)
  })

  it('true when running + connected + fresh + flow above threshold', () => {
    const snap = buildSnap({ valveInletFlow: FLOW_ANIMATION_THRESHOLD_M3S * 10 })
    expect(shouldShowFlowAnimation(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'connected', false, 'inlet',
    )).toBe(true)
  })
})

describe('formatRuntimeNumber', () => {
  it('shows dash for null', () => {
    expect(formatRuntimeNumber(null)).toBe('—')
  })
  it('shows dash for non-finite', () => {
    expect(formatRuntimeNumber(NaN)).toBe('—')
    expect(formatRuntimeNumber(Infinity)).toBe('—')
  })
  it('formats with digits and unit', () => {
    expect(formatRuntimeNumber(1.23456, 3)).toBe('1.235')
    expect(formatRuntimeNumber(1.23456, 3, 'm')).toBe('1.235 m')
  })
})

describe('computeStaleThresholdMs', () => {
  it('uses 2s floor when cycleTime is very small', () => {
    expect(computeStaleThresholdMs(0.1)).toBe(2000)
  })
  it('uses 3x cycleTime when greater than 2s', () => {
    expect(computeStaleThresholdMs(1.0)).toBe(3000)
    expect(computeStaleThresholdMs(2.0)).toBe(6000)
  })
  it('handles invalid cycleTime', () => {
    expect(computeStaleThresholdMs(0)).toBe(2000)
    expect(computeStaleThresholdMs(NaN)).toBe(2000)
  })
})

describe('selectPipeFlow', () => {
  it('returns valve.outlet_flow for valveToTank1 pipe', () => {
    const snap = buildSnap({ valveOutletFlow: 0.0005 })
    const flow = selectPipeFlow(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'valveToTank1',
    )
    expect(flow).toBe(0.0005)
  })
  it('returns valve.inlet_flow for inlet pipe', () => {
    const snap = buildSnap({ valveInletFlow: 0.001 })
    const flow = selectPipeFlow(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
      'inlet',
    )
    expect(flow).toBe(0.001)
  })
})

// 阶段 4 严要求：所有运行态显示字段只能来自 snapshot，禁止 draft 冒充实时值。
describe('selectSourceFlow / selectPIDSetpoint / selectPIDMode', () => {
  it('selectSourceFlow returns snapshot.sourceFlow in running state, NOT draft.sourceFlow', () => {
    const snap = buildSnap({ sourceFlow: 0.002 }) // ≠ draft (0.0012)
    const r = selectSourceFlow(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
    )
    expect(r.value).toBe(0.002)
    expect(r.present).toBe(true)
  })

  it('selectSourceFlow returns null in running state when sourceFlow missing (NOT draft fallback)', () => {
    const snap = buildSnap({})
    snap.sourceFlow = undefined as any
    const r = selectSourceFlow(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
    )
    // 严禁回退到 draft.sourceFlow (0.0012 m³/s)
    expect(r.value).toBeNull()
    expect(r.present).toBe(false)
  })

  it('selectPIDSetpoint uses snapshot.pid.SV in running, NOT draft.pid.SV', () => {
    const snap = buildSnap({ pidSV: 0.5 }) // ≠ draft (0.8)
    const r = selectPIDSetpoint(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
    )
    expect(r.value).toBe(0.5)
  })

  it('selectPIDMode uses snapshot.pid.MODE in running, NOT draft.pid.MODE', () => {
    const snap = buildSnap({})
    snap.pid.MODE = 4 // MAN, ≠ draft (5 AUTO)
    const r = selectPIDMode(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
    )
    expect(r.value).toBe(4)
  })

  it('selectPIDMode returns null when MODE missing in running (NOT fallback to draft 5=AUTO)', () => {
    const snap = buildSnap({})
    snap.pid.MODE = undefined as any
    const r = selectPIDMode(
      { runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft },
    )
    expect(r.value).toBeNull()
    expect(r.present).toBe(false)
  })

  it('selectValveOpening ALWAYS uses current_opening in running (NEVER target_opening)', () => {
    const snap = buildSnap({ valveCurrentOpening: 33.5, valveTargetOpening: 80 })
    const r = selectValveOpening({
      runtimeState: 'SIMULATION_RUNNING', latestSnapshot: snap, draft: baseDraft,
    })
    // 即便 target_opening ≠ current_opening，也必须用 current_opening
    expect(r.value).toBe(33.5)
  })
})

// helper: build a minimal RuntimeSnapshot for tests
function buildSnap(opts: {
  tank1Level?: number
  tank2Level?: number
  valveCurrentOpening?: number
  valveTargetOpening?: number
  valveInletFlow?: number
  valveOutletFlow?: number
  sourceFlow?: number
  pidSV?: number
  pidMV?: number
}) {
  return {
    cycleCount: 1,
    simTime: 0.5,
    sourceFlow: opts.sourceFlow ?? 0.0012,
    valve: {
      targetOpening: opts.valveTargetOpening ?? 50,
      currentOpening: opts.valveCurrentOpening ?? 30,
      inletFlow: opts.valveInletFlow ?? 0,
      outletFlow: opts.valveOutletFlow ?? 0,
    },
    tank1: {
      level: opts.tank1Level ?? 0.15,
      inletFlow: 0,
      outletFlow: 0,
    },
    tank2: {
      level: opts.tank2Level ?? 0.1,
      inletFlow: 0,
      outletFlow: 0,
    },
    pid: {
      PV: 0.1, SV: opts.pidSV ?? 0.8, CSV: 0, MV: opts.pidMV ?? 0,
      PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1,
    },
    _receivedAt: 0,
  }
}
