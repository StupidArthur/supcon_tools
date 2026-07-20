/**
 * Stage 5 prospective: submitAtomicWrites behavioral contracts (mock fetch).
 * See CONTRACT_SURFACES.md.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadWrites(contractId: string) {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'runtime', 'runtimeWrites')),
    contractId,
    'Public submitAtomicWrites({ apiHost, apiPort, runtimeName, writes }) → pending batch.',
  )
}

describe('stage 5 runtime writes acceptance', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('posts entire batch to /writes using runtimeName from caller', async () => {
    const mod = await loadWrites('STAGE5-ATOMIC-001')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, batch_id: 'b1', status: 'pending' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const submit = mod.submitAtomicWrites as (args: Record<string, unknown>) => Promise<unknown>
    const result = (await submit({
      apiHost: '127.0.0.1',
      apiPort: 8000,
      runtimeName: 'acceptance_runtime',
      writes: [
        { tag: 'pid2.SV', value: 0.8 },
        { tag: 'pid2.PB', value: 20 },
      ],
    })) as { status: string; batchId?: string; batch_id?: string }
    expect(result.status).toBe('pending')
    const url = String(fetchMock.mock.calls[0][0])
    expect(url, 'STAGE5-ATOMIC-001').toContain('/writes')
    expect(url, 'STAGE5-ATOMIC-014').not.toContain('/params')
    expect(url, 'STAGE5-ATOMIC-010').toContain('acceptance_runtime')
    expect(url).not.toContain('/pid2/')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(init.body))
    expect(body.writes).toHaveLength(2)
  })

  it('does not fetch when client precheck fails', async () => {
    const mod = await loadWrites('STAGE5-ATOMIC-002')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const submit = mod.submitAtomicWrites as (args: Record<string, unknown>) => Promise<unknown>
    await expect(
      submit({
        apiHost: '127.0.0.1',
        apiPort: 8000,
        runtimeName: 'acceptance_runtime',
        writes: [
          { tag: 'pid2.SV', value: 0.8 },
          { tag: 'unknown.tag', value: 1 },
        ],
      }),
    ).rejects.toBeTruthy()
    expect(fetchMock, 'STAGE5-ATOMIC-002: no fetch on precheck failure').not.toHaveBeenCalled()
  })

  it('stays pending until full snapshot confirm; timeout → failed', async () => {
    const mod = await loadWrites('STAGE5-ATOMIC-011')
    const observe = mod.observeWriteBatch as
      | ((input: {
          batchId: string
          snapshot: Record<string, number>
          expected: Record<string, number>
          timedOut?: boolean
        }) => string)
      | undefined
    expect(observe, 'STAGE5-ATOMIC-011: observeWriteBatch public helper required').toBeTypeOf(
      'function',
    )
    expect(
      observe!({
        batchId: 'b1',
        snapshot: { 'pid2.SV': 0.8 },
        expected: { 'pid2.SV': 0.8, 'pid2.PB': 20 },
      }),
      'STAGE5-ATOMIC-011: partial confirm stays pending',
    ).toBe('pending')
    expect(
      observe!({
        batchId: 'b1',
        snapshot: { 'pid2.SV': 0.8, 'pid2.PB': 20 },
        expected: { 'pid2.SV': 0.8, 'pid2.PB': 20 },
      }),
      'STAGE5-ATOMIC-012',
    ).toBe('applied')
    expect(
      observe!({
        batchId: 'b1',
        snapshot: {},
        expected: { 'pid2.SV': 0.8 },
        timedOut: true,
      }),
      'STAGE5-ATOMIC-013',
    ).toBe('failed')
  })
})
