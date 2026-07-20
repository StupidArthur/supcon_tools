/**
 * Stage 5 prospective: writeback behavioral contracts via public store/module actions.
 */
import { describe, expect, it, vi } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadWriteback(contractId: string) {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'writeback')),
    contractId,
    'Public writeback actions: runtimeOverrides must not mutate draft; whitelist save.',
  )
}

describe('stage 5 writeback acceptance', () => {
  it('runtimeOverrides do not change draft', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-001')
    const getDraft = mod.getDraft as () => unknown
    const apply = mod.applyRuntimeOverride as (tag: string, value: number) => void
    const before = structuredClone(getDraft())
    apply('pid2.SV', 0.55)
    expect(getDraft(), 'STAGE5-WRITEBACK-001').toEqual(before)
  })

  it('forbids selecting PV and realtime field writeback; MV default off', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-003')
    const selectable = mod.listWritebackCandidates as () => Array<{ tag: string; selected: boolean }>
    expect(selectable, 'STAGE5-WRITEBACK-003').toBeTypeOf('function')
    const items = selectable()
    const tags = items.map((i) => i.tag)
    expect(tags).not.toContain('PV')
    expect(tags).not.toContain('tank_2.level')
    expect(tags).not.toContain('valve_1.current_opening')
    const mv = items.find((i) => i.tag === 'MV' || i.tag === 'pid2.MV')
    if (mv) {
      expect(mv.selected, 'STAGE5-WRITEBACK-003: MV default unselected').toBe(false)
    }
  })

  it('failed save does not update saved; success keeps running identity', async () => {
    const mod = await loadWriteback('STAGE5-WRITEBACK-004')
    const save = mod.saveWriteback as (opts: { fail?: boolean }) => Promise<{
      savedUpdated: boolean
      runningIdentity: unknown
    }>
    expect(save, 'STAGE5-WRITEBACK-004').toBeTypeOf('function')
    const failed = await save({ fail: true })
    expect(failed.savedUpdated, 'STAGE5-WRITEBACK-004').toBe(false)
    const identityBefore = failed.runningIdentity
    const ok = await save({ fail: false })
    expect(ok.savedUpdated, 'STAGE5-WRITEBACK-005').toBe(true)
    expect(ok.runningIdentity, 'STAGE5-WRITEBACK-005: running identity unchanged').toEqual(
      identityBefore,
    )
  })
})
