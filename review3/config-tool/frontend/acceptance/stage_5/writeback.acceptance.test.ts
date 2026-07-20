/**
 * Stage 5 prospective acceptance: runtimeOverrides writeback to DSL.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadWriteback(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'writeback')),
    contractId,
    'runtimeOverrides must stay separate from draft; whitelist-only save.',
  )
}

describe('stage 5 writeback acceptance', () => {
  it('keeps runtimeOverrides separate from draft', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-001')
    expect(mod.applyRuntimeOverride, 'STAGE5-WRITEBACK-001').toBeTypeOf('function')
    expect(mod.getDraft, 'STAGE5-WRITEBACK-001: draft accessor required for isolation assert').toBeTypeOf(
      'function',
    )
    const draftBefore = structuredClone((mod.getDraft as () => unknown)())
    ;(mod.applyRuntimeOverride as (tag: string, value: number) => void)('pid2.SV', 0.55)
    expect(
      (mod.getDraft as () => unknown)(),
      'STAGE5-WRITEBACK-001: online write must not mutate draft',
    ).toEqual(draftBefore)
  })

  it('only allows whitelist fields for DSL writeback', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-002')
    const whitelist = mod.WRITEBACK_WHITELIST as string[] | undefined
    expect(whitelist, 'STAGE5-WRITEBACK-002: WRITEBACK_WHITELIST required').toEqual(
      expect.arrayContaining(['PB', 'TI', 'TD', 'KD', 'SV', 'MODE', 'SWPN']),
    )
    expect(whitelist, 'STAGE5-WRITEBACK-003: PV forbidden').not.toEqual(
      expect.arrayContaining(['PV']),
    )
  })

  it('forbids PV, realtime levels, realtime valve opening; MV defaults off', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-003')
    const forbidden = mod.WRITEBACK_FORBIDDEN as string[] | undefined
    expect(forbidden, 'STAGE5-WRITEBACK-003').toEqual(
      expect.arrayContaining([
        'PV',
        'tank_1.level',
        'tank_2.level',
        'valve_1.current_opening',
      ]),
    )
    const defaults = mod.WRITEBACK_DEFAULTS as { includeMV?: boolean } | undefined
    expect(defaults?.includeMV, 'STAGE5-WRITEBACK-003: MV default must be no writeback').toBe(false)
  })

  it('revalidates before saving writeback to DSL', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-004')
    expect(mod.revalidateBeforeWriteback, 'STAGE5-WRITEBACK-004').toBeTypeOf('function')
  })

  it('keeps saved vs running diff visible after successful writeback save', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-005')
    expect(mod.diffSavedVsRunning, 'STAGE5-WRITEBACK-005').toBeTypeOf('function')
  })
})
