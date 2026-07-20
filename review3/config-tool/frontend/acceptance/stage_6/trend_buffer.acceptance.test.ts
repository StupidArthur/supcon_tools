/**
 * Stage 6 prospective acceptance: TrendBuffer capacity and hygiene contracts.
 */
import { describe, expect, it } from 'vitest'
import type { RuntimeSnapshot } from '../../src/features/runtime/types'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

function makeSnap(cycleCount: number, overrides: Partial<RuntimeSnapshot> = {}): RuntimeSnapshot {
  return {
    cycleCount,
    simTime: cycleCount * 0.5,
    sourceFlow: 0.0012,
    valve: { currentOpening: 30, targetOpening: 50 },
    tank1: { level: 0.4 },
    tank2: { level: 0.6 },
    pid: { PV: 0.6, SV: 0.8, MV: 30 },
    _receivedAt: Date.now(),
    ...overrides,
  }
}

describe('stage 6 trend buffer acceptance', () => {
  it('defaults capacity to 1200 and drops oldest while preserving order', async () => {
    const { TrendBuffer } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(1200)
    expect(buf.size(), 'STAGE6-TREND-001').toBe(0)
    for (let i = 1; i <= 1205; i++) {
      buf.push(makeSnap(i), ['tank_2.level', 'pid2.SV'])
    }
    expect(buf.size(), 'STAGE6-TREND-001: max 1200 real snapshots').toBe(1200)
    const arr = buf.toArray()
    expect(arr[0].cycleCount, 'STAGE6-TREND-002: drop oldest').toBe(6)
    expect(arr[arr.length - 1].cycleCount, 'STAGE6-TREND-002: order preserved').toBe(1205)
    for (let i = 1; i < arr.length; i++) {
      expect((arr[i].cycleCount ?? 0) > (arr[i - 1].cycleCount ?? 0), 'STAGE6-TREND-002').toBe(
        true,
      )
    }
  })

  it('does not accept NaN/Infinity as finite series values', async () => {
    const { TrendBuffer, readTag } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(10)
    const snap = makeSnap(1, {
      tank2: { level: Number.NaN },
      pid: { SV: Number.POSITIVE_INFINITY, MV: 10 },
    })
    buf.push(snap, ['tank_2.level', 'pid2.SV', 'pid2.MV'])
    const point = buf.toArray()[0]
    expect(point.values['tank_2.level'], 'STAGE6-TREND-003').toBeNull()
    expect(point.values['pid2.SV'], 'STAGE6-TREND-003').toBeNull()
    expect(readTag(snap, 'pid2.MV'), 'STAGE6-TREND-003').toBe(10)
  })

  it('rotateOut archives previous run without mixing runtime identities', async () => {
    const { TrendBuffer } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(10)
    buf.push(makeSnap(1), ['tank_2.level'])
    const previous = buf.rotateOut()
    expect(previous.length, 'STAGE6-TREND-004: restart archives previousRunSeries').toBe(1)
    expect(buf.size(), 'STAGE6-TREND-004').toBe(0)
    buf.push(makeSnap(1), ['tank_2.level'])
    expect(buf.toArray()[0].cycleCount, 'STAGE6-TREND-005: new runtime series separate').toBe(1)
  })

  it('store policy: Stop must not auto-clear; stale/heartbeat must not append', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'runtime', 'trendPolicy')),
      'STAGE6-TREND-006',
      'Required: heartbeat/stale do not append; Stop does not auto-clear; runtime instances must not mix.',
    )
    expect(mod.shouldAppendSnapshot, 'STAGE6-TREND-006').toBeTypeOf('function')
    const shouldAppend = mod.shouldAppendSnapshot as (input: {
      heartbeat?: boolean
      stale?: boolean
    }) => boolean
    expect(shouldAppend({ heartbeat: true }), 'STAGE6-TREND-006: heartbeat not plotted').toBe(false)
    expect(shouldAppend({ stale: true }), 'STAGE6-TREND-006: stale not appended').toBe(false)
    expect(mod.clearOnStop, 'STAGE6-TREND-007: Stop must not auto-clear').toBe(false)
  })
})
