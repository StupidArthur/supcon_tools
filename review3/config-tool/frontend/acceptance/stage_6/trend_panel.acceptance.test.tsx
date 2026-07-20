/**
 * Stage 6 prospective: RuntimeTrendPanel render contracts (axes, PV binding, toggles).
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

describe('stage 6 trend panel acceptance', () => {
  it('shows dual-axis grouping, PV binding note, and series toggles', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'RuntimeTrendPanel')),
      'STAGE6-TREND-010',
      'RuntimeTrendPanel public UI: left tank_2.level+SV, right MV+current_opening, PV←tank_2 note.',
    )
    const { render, screen } = await import('@testing-library/react')
    const Panel = mod.RuntimeTrendPanel as React.FC<Record<string, unknown>>
    render(
      <Panel
        series={[]}
        previousRunSeries={[{ cycleCount: 1, simTime: 0.5, values: { 'tank_2.level': 0.1 } }]}
        events={[]}
        stale={false}
      />,
    )
    expect(screen.getByTestId('trend-axis-left').textContent, 'STAGE6-TREND-011').toMatch(
      /tank_2\.level|SV/i,
    )
    expect(screen.getByTestId('trend-axis-right').textContent, 'STAGE6-TREND-011').toMatch(
      /MV|current_opening/i,
    )
    expect(screen.getByTestId('trend-pv-binding').textContent, 'STAGE6-TREND-012').toContain(
      'pid2.PV ← tank_2.level',
    )
    expect(screen.getByTestId('trend-series-toggles'), 'STAGE6-TREND-013').toBeTruthy()
    expect(screen.getByTestId('trend-previous-run-secondary'), 'STAGE6-TREND-013').toBeTruthy()
  })
})
