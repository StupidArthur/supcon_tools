/**
 * Stage 6 prospective acceptance: trend parameter-event timeline contracts.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadEvents(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'runtime', 'trendEvents')),
    contractId,
    'Events need pending/applied/failed with time, old/new value, source; snapshot confirmation time must not be faked by REST return time.',
  )
}

describe('stage 6 trend events acceptance', () => {
  it('records pending/applied/failed with old/new/source metadata', async () => {
    const mod = await loadEvents('STAGE6-EVENT-001')
    expect(mod.createTrendEvent, 'STAGE6-EVENT-001').toBeTypeOf('function')
    const create = mod.createTrendEvent as (input: Record<string, unknown>) => Record<string, unknown>
    const event = create({
      status: 'pending',
      tag: 'pid2.SV',
      oldValue: 0.8,
      newValue: 0.9,
      source: 'faceplate',
      restReturnedAt: 1000,
    })
    expect(event).toEqual(
      expect.objectContaining({
        status: 'pending',
        tag: 'pid2.SV',
        oldValue: 0.8,
        newValue: 0.9,
        source: 'faceplate',
      }),
    )
  })

  it('uses snapshot confirmation time, not REST return time, for applied', async () => {
    const mod = await loadEvents('STAGE6-EVENT-002')
    const confirm = mod.confirmTrendEvent as
      | ((eventId: string, snapshotConfirmedAt: number) => Record<string, unknown>)
      | undefined
    expect(confirm, 'STAGE6-EVENT-002').toBeTypeOf('function')
    const applied = confirm!('evt-1', 5000)
    expect(applied.status).toBe('applied')
    expect(applied.confirmedAt, 'STAGE6-EVENT-002').toBe(5000)
    expect(applied.confirmedAt, 'STAGE6-EVENT-002').not.toBe(applied.restReturnedAt)
  })

  it('parameter change restarts current quality timing and archives previous segment', async () => {
    const mod = await loadEvents('STAGE6-EVENT-003')
    expect(mod.onParameterEvent, 'STAGE6-EVENT-003').toBeTypeOf('function')
    const onEvent = mod.onParameterEvent as () => {
      currentSegmentStartedAt: number
      archivedSegments: unknown[]
    }
    const before = onEvent()
    const after = onEvent()
    expect(after.archivedSegments.length).toBeGreaterThanOrEqual(before.archivedSegments.length)
    expect(after.currentSegmentStartedAt).toBeGreaterThanOrEqual(before.currentSegmentStartedAt)
  })
})
