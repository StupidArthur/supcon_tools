/**
 * Stage 6 prospective: TrendBuffer behavioral contracts (existing public class).
 * Store policy (stop/stale/heartbeat) asserted via RuntimeTrendPanel / store observables when present.
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
  it('capacity 1200 drops oldest and keeps order', async () => {
    const { TrendBuffer } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(1200)
    for (let i = 1; i <= 1205; i++) buf.push(makeSnap(i), ['tank_2.level'])
    expect(buf.size(), 'STAGE6-TREND-001').toBe(1200)
    const arr = buf.toArray()
    expect(arr[0].cycleCount, 'STAGE6-TREND-002').toBe(6)
    expect(arr.at(-1)?.cycleCount, 'STAGE6-TREND-002').toBe(1205)
  })

  it('NaN/Infinity become null in series values', async () => {
    const { TrendBuffer } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(10)
    buf.push(
      makeSnap(1, { tank2: { level: Number.NaN }, pid: { SV: Number.POSITIVE_INFINITY } }),
      ['tank_2.level', 'pid2.SV'],
    )
    expect(buf.toArray()[0].values['tank_2.level'], 'STAGE6-TREND-003').toBeNull()
    expect(buf.toArray()[0].values['pid2.SV'], 'STAGE6-TREND-003').toBeNull()
  })

  it('rotateOut archives previous run series', async () => {
    const { TrendBuffer } = await import('../../src/features/runtime/trendBuffer')
    const buf = new TrendBuffer(10)
    buf.push(makeSnap(1), ['tank_2.level'])
    const prev = buf.rotateOut()
    expect(prev.length, 'STAGE6-TREND-004').toBe(1)
    expect(buf.size(), 'STAGE6-TREND-004').toBe(0)
  })

  it('panel freezes append/animation when stale (public UI behavior)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'RuntimeTrendPanel')),
      'STAGE6-TREND-006',
      'RuntimeTrendPanel must freeze plotting/animation when stale; heartbeat must not append points.',
    )
    const { render, screen } = await import('@testing-library/react')
    const Panel = mod.RuntimeTrendPanel as React.FC<Record<string, unknown>>
    render(
      <Panel
        series={[]}
        previousRunSeries={[]}
        events={[]}
        stale
        connectionState="disconnected"
      />,
    )
    expect(screen.getByTestId('trend-stale-frozen'), 'STAGE6-TREND-006').toBeTruthy()
  })
})
