/**
 * Stage 7 prospective: dirty/validation/realtime mutex state machine.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

describe('stage 7 batch state acceptance', () => {
  it('blocks batch when dirty or invalid; blocks realtime when BATCH_RUNNING', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'batchState')),
      'STAGE7-STATE-001',
      'Public canStartBatch / canStartRealtime pure helpers.',
    )
    const canStartBatch = mod.canStartBatch as (s: Record<string, unknown>) => boolean
    const canStartRealtime = mod.canStartRealtime as (s: Record<string, unknown>) => boolean
    expect(canStartBatch({ dirty: true, valid: true, runtimeState: 'STOPPED_EDITING' }), 'STAGE7-STATE-001').toBe(
      false,
    )
    expect(
      canStartBatch({ dirty: false, valid: false, runtimeState: 'STOPPED_EDITING' }),
      'STAGE7-STATE-002',
    ).toBe(false)
    expect(
      canStartRealtime({ runtimeState: 'BATCH_RUNNING' }),
      'STAGE7-STATE-003',
    ).toBe(false)
    expect(
      canStartBatch({ dirty: false, valid: true, runtimeState: 'SIMULATION_RUNNING' }),
      'STAGE7-STATE-004',
    ).toBe(false)
    expect(
      canStartBatch({ dirty: false, valid: true, runtimeState: 'STOPPED_EDITING' }),
      'STAGE7-STATE-005',
    ).toBe(true)
  })
})
