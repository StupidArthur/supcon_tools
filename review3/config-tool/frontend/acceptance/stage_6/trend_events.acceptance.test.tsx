/**
 * Stage 6 prospective: trend events via public UI/store — snapshot confirm time, not REST time.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

describe('stage 6 trend events acceptance', () => {
  it('renders pending/applied/failed with metadata; applied uses snapshot time', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'RuntimeTrendPanel')),
      'STAGE6-EVENT-001',
      'Trend event list must show pending/applied/failed with old/new/source; confirmedAt from snapshot.',
    )
    const { render, screen } = await import('@testing-library/react')
    const Panel = mod.RuntimeTrendPanel as React.FC<Record<string, unknown>>
    render(
      <Panel
        series={[]}
        previousRunSeries={[]}
        stale={false}
        events={[
          {
            id: 'e1',
            status: 'pending',
            tag: 'pid2.SV',
            oldValue: 0.8,
            newValue: 0.9,
            source: 'faceplate',
            restReturnedAt: 1000,
          },
          {
            id: 'e2',
            status: 'applied',
            tag: 'pid2.PB',
            oldValue: 30,
            newValue: 25,
            source: 'faceplate',
            restReturnedAt: 1000,
            confirmedAt: 5000,
          },
        ]}
      />,
    )
    expect(screen.getByTestId('trend-event-e1').textContent?.toLowerCase()).toContain('pending')
    const applied = screen.getByTestId('trend-event-e2')
    expect(applied.textContent?.toLowerCase()).toContain('applied')
    expect(applied.getAttribute('data-confirmed-at'), 'STAGE6-EVENT-002').toBe('5000')
    expect(applied.getAttribute('data-confirmed-at'), 'STAGE6-EVENT-002').not.toBe('1000')
  })
})
