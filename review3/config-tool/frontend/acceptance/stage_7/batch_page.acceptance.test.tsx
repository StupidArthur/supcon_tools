/**
 * Stage 7 prospective: Batch page UI discovery and failure presentation.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

describe('stage 7 batch page acceptance', () => {
  it('batch entry lives on template page with progress/failure/export', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'BatchPanel')),
      'STAGE7-BATCH-001',
      'Public BatchPanel on same template page: progress, failure, result, CSV export.',
    )
    const { render, screen } = await import('@testing-library/react')
    const BatchPanel = mod.BatchPanel as React.FC<Record<string, unknown>>
    render(
      <BatchPanel
        status="failed"
        error="engine exit 2"
        progress={0.4}
        resultPoints={[]}
        exportPath=""
      />,
    )
    expect(screen.getByTestId('batch-entry'), 'same-page entry').toBeTruthy()
    expect(screen.getByTestId('batch-progress')).toBeTruthy()
    expect(screen.getByTestId('batch-error').textContent).toContain('exit 2')
    expect(screen.queryByTestId('batch-empty-success-chart')).toBeNull()
    expect(screen.getByTestId('batch-export-csv')).toBeTruthy()
  })
})
