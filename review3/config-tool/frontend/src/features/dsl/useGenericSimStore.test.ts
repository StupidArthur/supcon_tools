/**
 * Unit tests for generic offline simulation store (project-bound).
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useGenericSimStore } from './useGenericSimStore'

describe('useGenericSimStore', () => {
  beforeEach(() => {
    useGenericSimStore.getState().clearResults()
    useGenericSimStore.getState().setCycles(2000)
  })

  it('only commits results when project/run/epoch match', () => {
    const epoch = useGenericSimStore.getState().epoch
    const runId = useGenericSimStore.getState().beginRun({
      projectId: 'p1',
      yamlHash: 'h1',
      cycles: 100,
      epoch,
    })
    expect(useGenericSimStore.getState().status).toBe('running')

    const ok = useGenericSimStore.getState().succeed({
      projectId: 'p1',
      runId,
      epoch,
      columns: ['_cycle', 'level'],
      rows: [{ _cycle: 0, level: 1.2 }],
      completedCycles: 1,
    })
    expect(ok).toBe(true)
    expect(useGenericSimStore.getState().hasExportableResult('p1')).toBe(true)
    expect(useGenericSimStore.getState().hasExportableResult('p2')).toBe(false)
  })

  it('rejects stale late succeed after project switch clear', () => {
    const epoch = useGenericSimStore.getState().epoch
    const runId = useGenericSimStore.getState().beginRun({
      projectId: 'p1',
      yamlHash: 'h1',
      cycles: 10,
      epoch,
    })
    useGenericSimStore.getState().clearResults()
    const ok = useGenericSimStore.getState().succeed({
      projectId: 'p1',
      runId,
      epoch,
      columns: ['_cycle'],
      rows: [{ _cycle: 0 }],
      completedCycles: 1,
    })
    expect(ok).toBe(false)
    expect(useGenericSimStore.getState().rows).toEqual([])
  })

  it('marks success stale after YAML edit', () => {
    const epoch = useGenericSimStore.getState().epoch
    const runId = useGenericSimStore.getState().beginRun({
      projectId: 'p1',
      yamlHash: 'h1',
      cycles: 10,
      epoch,
    })
    useGenericSimStore.getState().succeed({
      projectId: 'p1',
      runId,
      epoch,
      columns: ['_cycle', 'x'],
      rows: [{ _cycle: 0, x: 1 }],
      completedCycles: 1,
    })
    useGenericSimStore.getState().markStale()
    expect(useGenericSimStore.getState().stale).toBe(true)
    expect(useGenericSimStore.getState().hasExportableResult('p1')).toBe(false)
    expect(useGenericSimStore.getState().hasDisplayResult('p1')).toBe(true)
  })
})
