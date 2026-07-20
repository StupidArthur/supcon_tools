/**
 * Stage 5 prospective acceptance: frontend atomic write client contracts.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadWritesApi(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'runtime', 'runtimeWrites')),
    contractId,
    'Required: submitAtomicWrites → /writes, pending until snapshot applied.',
  )
}

describe('stage 5 runtime writes acceptance', () => {
  it('submitAtomicWrites posts to /writes not /params', async () => {
    const mod = await loadWritesApi('STAGE5-ATOMIC-001')
    expect(mod.submitAtomicWrites, 'STAGE5-ATOMIC-001: submitAtomicWrites required').toBeTypeOf(
      'function',
    )
    const pathBuilder = mod.buildWritesPath as ((runtimeName: string) => string) | undefined
    expect(pathBuilder, 'STAGE5-ATOMIC-001: buildWritesPath required').toBeTypeOf('function')
    const built = pathBuilder!('second_order_tank')
    expect(built, 'STAGE5-ATOMIC-001').toContain('/writes')
    expect(built, 'STAGE5-ATOMIC-014: must not default to /params').not.toContain('/params')
  })

  it('rejects client-side partial batches before POST', async () => {
    const mod = await loadWritesApi('STAGE5-ATOMIC-002')
    const validate = mod.validateWriteBatch as
      | ((writes: unknown[]) => { ok: boolean; reason?: string })
      | undefined
    expect(validate, 'STAGE5-ATOMIC-002: validateWriteBatch required').toBeTypeOf('function')
    const result = validate!([
      { tag: 'pid2.SV', value: 0.8 },
      { tag: 'unknown.tag', value: 1 },
    ])
    expect(result.ok, 'STAGE5-ATOMIC-003: any invalid field rejects entire batch').toBe(false)
  })

  it('maps REST success to pending and snapshot confirm to applied', async () => {
    const mod = await loadWritesApi('STAGE5-ATOMIC-011')
    const mapStatus = mod.mapWriteLifecycle as
      | ((input: { restOk: boolean; snapshotConfirmed: boolean; timedOut: boolean }) => string)
      | undefined
    expect(mapStatus, 'STAGE5-ATOMIC-011: mapWriteLifecycle required').toBeTypeOf('function')
    expect(mapStatus!({ restOk: true, snapshotConfirmed: false, timedOut: false })).toBe('pending')
    expect(mapStatus!({ restOk: true, snapshotConfirmed: true, timedOut: false })).toBe('applied')
    expect(
      mapStatus!({ restOk: true, snapshotConfirmed: false, timedOut: true }),
      'STAGE5-ATOMIC-013',
    ).toBe('failed')
  })

  it('keeps runtimeName distinct from pid2 program name', async () => {
    const mod = await loadWritesApi('STAGE5-ATOMIC-010')
    const resolve = mod.resolveWriteRuntimeName as
      | ((statusInstanceName: string) => string)
      | undefined
    expect(resolve, 'STAGE5-ATOMIC-010: resolveWriteRuntimeName required').toBeTypeOf('function')
    expect(resolve!('second_order_tank')).toBe('second_order_tank')
    expect(resolve!('second_order_tank')).not.toBe('pid2')
  })
})
