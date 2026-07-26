import { describe, expect, it, vi } from 'vitest'
import {
  getCollectionNotices,
  startRecentTimer,
  type CollectionHealth,
} from '@/components/CollectionHealthNotice'

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
    missingNodeCount: 0,
    staleWorkerCount: 0,
    staleActorCount: 0,
    clusterDataStale: false,
    jobsDataStale: false,
    currentStorageError: false,
    lastStorageErrorTs: 0,
    lastStorageError: '',
    failedNodes: [],
    ...overrides,
  }
}

describe('getCollectionNotices', () => {
  it('returns no notices without health or failures', () => {
    expect(getCollectionNotices(undefined, 1)).toEqual([])
    expect(getCollectionNotices(makeHealth(), 1)).toEqual([])
  })

  it.each([
    [{ failedNodeCount: 1, staleNodeCount: 1, currentIncomplete: true }, ['node-detail']],
    [{ failedNodeCount: 1, missingNodeCount: 1, currentIncomplete: true }, ['node-detail']],
    [{ clusterDataStale: true, currentIncomplete: true }, ['cluster']],
    [{ jobsDataStale: true, currentIncomplete: true }, ['jobs']],
    [{ currentStorageError: true }, ['storage']],
  ])('identifies a single failure reason', (overrides, expected) => {
    expect(getCollectionNotices(makeHealth(overrides), 1)).toEqual(expected)
  })

  it.each([
    [
      { failedNodeCount: 1, clusterDataStale: true, currentIncomplete: true },
      ['node-detail', 'cluster'],
    ],
    [
      { failedNodeCount: 1, jobsDataStale: true, currentIncomplete: true },
      ['node-detail', 'jobs'],
    ],
    [
      { failedNodeCount: 1, currentStorageError: true, currentIncomplete: true },
      ['node-detail', 'storage'],
    ],
    [
      { clusterDataStale: true, jobsDataStale: true, currentStorageError: true, currentIncomplete: true },
      ['cluster', 'jobs', 'storage'],
    ],
  ])('preserves combined failure reasons', (overrides, expected) => {
    expect(getCollectionNotices(makeHealth(overrides), 1)).toEqual(expected)
  })

  it('shows recovery at 30 and 60 seconds, then expires', () => {
    const now = 100_000
    expect(getCollectionNotices(makeHealth({ lastIncompleteTs: now - 30_000 }), now))
      .toEqual(['recent-recovered'])
    expect(getCollectionNotices(makeHealth({ lastIncompleteTs: now - 60_000 }), now))
      .toEqual(['recent-recovered'])
    expect(getCollectionNotices(makeHealth({ lastIncompleteTs: now - 60_001 }), now))
      .toEqual([])
  })

  it('does not describe current incomplete collection as recovered', () => {
    const now = 100_000
    const health = makeHealth({
      currentIncomplete: true,
      jobsDataStale: true,
      lastIncompleteTs: now - 30_000,
    })
    expect(getCollectionNotices(health, now)).toEqual(['jobs'])
  })

  it('clears the recovery timer on cleanup', () => {
    const timer = 17 as unknown as ReturnType<typeof setInterval>
    const setTimer = vi.fn(() => timer) as unknown as typeof setInterval
    const clearTimer = vi.fn() as unknown as typeof clearInterval
    const cleanup = startRecentTimer(() => {}, setTimer, clearTimer)
    cleanup()
    expect(setTimer).toHaveBeenCalledOnce()
    expect(clearTimer).toHaveBeenCalledWith(timer)
  })
})
