import { describe, it, expect } from 'vitest'
import { getCollectionNotice, type CollectionHealth } from '@/components/CollectionHealthNotice'

function makeHealth(overrides: Partial<CollectionHealth> = {}): CollectionHealth {
  return {
    lastDetailAttemptTs: 0,
    lastCompleteDetailSuccessTs: 0,
    lastIncompleteTs: 0,
    currentIncomplete: false,
    totalNodeCount: 3,
    freshNodeCount: 3,
    failedNodeCount: 0,
    staleNodeCount: 0,
    staleWorkerCount: 0,
    staleActorCount: 0,
    clusterDataStale: false,
    jobsDataStale: false,
    lastStorageErrorTs: 0,
    lastStorageError: '',
    failedNodes: [],
    ...overrides,
  }
}

describe('getCollectionNotice', () => {
  it('returns null when health is undefined', () => {
    expect(getCollectionNotice(undefined, Date.now())).toBeNull()
    expect(getCollectionNotice(null, Date.now())).toBeNull()
  })

  it('returns null when no failures ever', () => {
    const h = makeHealth()
    expect(getCollectionNotice(h, Date.now())).toBeNull()
  })

  it('returns active when currentIncomplete is true', () => {
    const h = makeHealth({ currentIncomplete: true, failedNodeCount: 1 })
    expect(getCollectionNotice(h, Date.now())).toBe('active')
  })

  it('returns storage when storage error exists', () => {
    const h = makeHealth({ lastStorageError: 'disk full', lastStorageErrorTs: Date.now() })
    expect(getCollectionNotice(h, Date.now())).toBe('storage')
  })

  it('returns recent within 60s after recovery', () => {
    const now = Date.now()
    const h = makeHealth({ lastIncompleteTs: now - 30_000 })
    expect(getCollectionNotice(h, now)).toBe('recent')
  })

  it('returns null after 60s since last incomplete', () => {
    const now = Date.now()
    const h = makeHealth({ lastIncompleteTs: now - 61_000 })
    expect(getCollectionNotice(h, now)).toBeNull()
  })

  it('returns recent at exactly 60s boundary', () => {
    const now = Date.now()
    const h = makeHealth({ lastIncompleteTs: now - 60_000 })
    expect(getCollectionNotice(h, now)).toBe('recent')
  })

  it('active takes priority over storage', () => {
    const h = makeHealth({
      currentIncomplete: true,
      lastStorageError: 'err',
      lastStorageErrorTs: Date.now(),
    })
    expect(getCollectionNotice(h, Date.now())).toBe('active')
  })

  it('failed nodes with cache are reported in active state', () => {
    const h = makeHealth({
      currentIncomplete: true,
      failedNodeCount: 1,
      failedNodes: [
        {
          nodeId: 'n1',
          nodeName: 'worker-1',
          lastAttemptTs: Date.now(),
          lastSuccessTs: Date.now() - 10000,
          lastFailureTs: Date.now(),
          consecutiveFailures: 2,
          lastError: 'timeout',
          currentStale: true,
          hasCachedData: true,
          reusedWorkerCount: 5,
          reusedActorCount: 3,
        },
      ],
    })
    expect(getCollectionNotice(h, Date.now())).toBe('active')
    expect(h.failedNodes[0].hasCachedData).toBe(true)
  })

  it('failed nodes without cache are reported', () => {
    const h = makeHealth({
      currentIncomplete: true,
      failedNodeCount: 1,
      failedNodes: [
        {
          nodeId: 'n2',
          nodeName: 'worker-2',
          lastAttemptTs: Date.now(),
          lastSuccessTs: 0,
          lastFailureTs: Date.now(),
          consecutiveFailures: 1,
          lastError: 'connection refused',
          currentStale: false,
          hasCachedData: false,
          reusedWorkerCount: 0,
          reusedActorCount: 0,
        },
      ],
    })
    expect(getCollectionNotice(h, Date.now())).toBe('active')
    expect(h.failedNodes[0].hasCachedData).toBe(false)
  })
})
