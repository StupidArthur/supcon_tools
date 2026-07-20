/**
 * Stage 5 prospective acceptance: PidFaceplate mode/edit/status contracts.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadFaceplate(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'PidFaceplate')),
    contractId,
    'Expected AUTO/MAN/CAS editability, pending/applied/failed statuses.',
  )
}

describe('stage 5 pid faceplate acceptance', () => {
  it('exports PidFaceplate component', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-001')
    expect(mod.PidFaceplate, 'STAGE5-MODE-001: PidFaceplate export required').toBeTypeOf('function')
  })

  it('AUTO: SV editable, MV locked', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-002')
    const policy = mod.FACEPLATE_MODE_POLICY as
      | { AUTO?: { svEditable?: boolean; mvEditable?: boolean } }
      | undefined
    expect(policy?.AUTO?.svEditable, 'STAGE5-MODE-002: AUTO SV must be editable').toBe(true)
    expect(policy?.AUTO?.mvEditable, 'STAGE5-MODE-002: AUTO MV must be locked').toBe(false)
  })

  it('MAN: MV editable; SV is not the actual manipulated value', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-003')
    const policy = mod.FACEPLATE_MODE_POLICY as
      | { MAN?: { mvEditable?: boolean; svIsManipulatedValue?: boolean } }
      | undefined
    expect(policy?.MAN?.mvEditable, 'STAGE5-MODE-003: MAN MV must be editable').toBe(true)
    expect(
      policy?.MAN?.svIsManipulatedValue,
      'STAGE5-MODE-003: MAN must not present SV as the actual manipulated value',
    ).toBe(false)
  })

  it('CAS: CSV is effective setpoint; SV is not displayed as effective', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-004')
    const policy = mod.FACEPLATE_MODE_POLICY as
      | { CAS?: { effectiveSetpoint?: string } }
      | undefined
    expect(policy?.CAS?.effectiveSetpoint, 'STAGE5-MODE-004: CAS effective setpoint is CSV').toBe(
      'CSV',
    )
  })

  it('exposes pending/applied/failed write status vocabulary', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-005')
    const statuses = mod.WRITE_STATUSES as string[] | undefined
    expect(statuses, 'STAGE5-MODE-005: WRITE_STATUSES required').toEqual(
      expect.arrayContaining(['pending', 'applied', 'failed']),
    )
  })

  it('covers PV SV CSV MV PB TI TD KD MODE SWPN fields', async () => {
    const mod = await loadFaceplate('STAGE5-MODE-006')
    const fields = mod.FACEPLATE_FIELDS as string[] | undefined
    expect(fields, 'STAGE5-MODE-006: FACEPLATE_FIELDS required').toEqual(
      expect.arrayContaining(['PV', 'SV', 'CSV', 'MV', 'PB', 'TI', 'TD', 'KD', 'MODE', 'SWPN']),
    )
  })
})
