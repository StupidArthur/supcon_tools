/**
 * Stage 6 prospective acceptance: RuntimeTrendPanel axis/grouping/stale contracts.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadPanel(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'RuntimeTrendPanel')),
    contractId,
    'Left axis: tank_2.level + SV; right axis: MV + valve current_opening; show pid2.PV ← tank_2.level; series toggles; freeze on stale.',
  )
}

describe('stage 6 trend panel acceptance', () => {
  it('exports RuntimeTrendPanel', async () => {
    const mod = await loadPanel('STAGE6-TREND-010')
    expect(mod.RuntimeTrendPanel, 'STAGE6-TREND-010').toBeTypeOf('function')
  })

  it('declares left/right axis groupings', async () => {
    const mod = await loadPanel('STAGE6-TREND-011')
    const axes = mod.TREND_AXIS_CONFIG as
      | { left?: string[]; right?: string[] }
      | undefined
    expect(axes?.left, 'STAGE6-TREND-011 left').toEqual(
      expect.arrayContaining(['tank_2.level', 'pid2.SV']),
    )
    expect(axes?.right, 'STAGE6-TREND-011 right').toEqual(
      expect.arrayContaining(['pid2.MV', 'valve_1.current_opening']),
    )
  })

  it('exposes PV binding note pid2.PV ← tank_2.level', async () => {
    const mod = await loadPanel('STAGE6-TREND-012')
    expect(mod.PV_BINDING_NOTE, 'STAGE6-TREND-012').toBe('pid2.PV ← tank_2.level')
  })

  it('supports series toggles and freezes append/animation when stale', async () => {
    const mod = await loadPanel('STAGE6-TREND-013')
    expect(mod.defaultSeriesVisibility, 'STAGE6-TREND-013 series toggles').toBeTypeOf('object')
    expect(mod.shouldAnimateTrend, 'STAGE6-TREND-013').toBeTypeOf('function')
    const shouldAnimate = mod.shouldAnimateTrend as (input: { stale: boolean }) => boolean
    expect(shouldAnimate({ stale: true }), 'STAGE6-TREND-013: stale freezes animation').toBe(false)
  })
})
