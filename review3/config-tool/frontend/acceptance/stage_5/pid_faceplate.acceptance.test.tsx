/**
 * Stage 5 prospective: PidFaceplate behavioral render contracts.
 * See CONTRACT_SURFACES.md — no internal FACEPLATE_* constant requirements.
 */
import { describe, expect, it, vi } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadFaceplateModule(contractId: string) {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'PidFaceplate')),
    contractId,
    'Public React component PidFaceplate with accessible SV/MV/CSV/PV controls.',
  )
}

describe('stage 5 pid faceplate acceptance', () => {
  it('AUTO: SV enabled, MV disabled; PV readonly', async () => {
    const mod = await loadFaceplateModule('STAGE5-MODE-002')
    const { render, screen } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    render(
      <PidFaceplate
        mode="AUTO"
        values={{ PV: 0.5, SV: 0.8, CSV: 0.7, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 }}
        writeStatus="idle"
        onSubmit={vi.fn()}
      />,
    )
    const sv = screen.getByTestId('faceplate-sv') as HTMLInputElement
    const mv = screen.getByTestId('faceplate-mv') as HTMLInputElement
    const pv = screen.getByTestId('faceplate-pv') as HTMLInputElement
    expect(sv.disabled, 'STAGE5-MODE-002: AUTO SV editable').toBe(false)
    expect(mv.disabled, 'STAGE5-MODE-002: AUTO MV locked').toBe(true)
    expect(pv.disabled || pv.readOnly, 'STAGE5-MODE-006: PV always readonly').toBe(true)
  })

  it('MAN: MV enabled; does not present SV as manipulated value', async () => {
    const mod = await loadFaceplateModule('STAGE5-MODE-003')
    const { render, screen } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    render(
      <PidFaceplate
        mode="MAN"
        values={{ PV: 0.5, SV: 0.8, CSV: 0.7, MV: 40, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 4, SWPN: 1 }}
        writeStatus="idle"
        onSubmit={vi.fn()}
      />,
    )
    const mv = screen.getByTestId('faceplate-mv') as HTMLInputElement
    expect(mv.disabled, 'STAGE5-MODE-003: MAN MV editable').toBe(false)
    expect(screen.queryByTestId('faceplate-effective-setpoint')?.textContent || '').not.toMatch(/SV\s*=\s*manipulat/i)
  })

  it('CAS: effective setpoint shows CSV not SV', async () => {
    const mod = await loadFaceplateModule('STAGE5-MODE-004')
    const { render, screen } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    render(
      <PidFaceplate
        mode="CAS"
        values={{ PV: 0.5, SV: 0.8, CSV: 0.55, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 3, SWPN: 1 }}
        writeStatus="idle"
        onSubmit={vi.fn()}
      />,
    )
    const effective = screen.getByTestId('faceplate-effective-setpoint')
    expect(effective.textContent, 'STAGE5-MODE-004').toContain('0.55')
    expect(effective.textContent, 'STAGE5-MODE-004: must not show SV as effective').not.toContain('0.80')
  })

  it('shows pending → applied → failed write statuses', async () => {
    const mod = await loadFaceplateModule('STAGE5-MODE-005')
    const { render, screen, rerender } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    const props = {
      mode: 'AUTO',
      values: { PV: 0.5, SV: 0.8, CSV: 0.7, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 },
      onSubmit: vi.fn(),
    }
    const { rerender: rr } = render(<PidFaceplate {...props} writeStatus="pending" />)
    expect(screen.getByTestId('faceplate-write-status').textContent?.toLowerCase()).toContain('pending')
    rr(<PidFaceplate {...props} writeStatus="applied" />)
    expect(screen.getByTestId('faceplate-write-status').textContent?.toLowerCase()).toContain('applied')
    rr(<PidFaceplate {...props} writeStatus="failed" writeError="timeout" />)
    expect(screen.getByTestId('faceplate-write-status').textContent?.toLowerCase()).toContain('failed')
  })

  it('covers all faceplate fields with labels', async () => {
    const mod = await loadFaceplateModule('STAGE5-MODE-006')
    const { render, screen } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    render(
      <PidFaceplate
        mode="AUTO"
        values={{ PV: 0.5, SV: 0.8, CSV: 0.7, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 }}
        writeStatus="idle"
        onSubmit={vi.fn()}
      />,
    )
    for (const id of [
      'faceplate-pv',
      'faceplate-sv',
      'faceplate-csv',
      'faceplate-mv',
      'faceplate-pb',
      'faceplate-ti',
      'faceplate-td',
      'faceplate-kd',
      'faceplate-mode',
      'faceplate-swpn',
    ]) {
      expect(screen.getByTestId(id), `STAGE5-MODE-006: ${id}`).toBeTruthy()
    }
  })
})
