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
      currentYamlHash: 'h1',
    })
    expect(ok).toBe(true)
    expect(useGenericSimStore.getState().stale).toBe(false)
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
      currentYamlHash: 'h1',
    })
    expect(ok).toBe(false)
    expect(useGenericSimStore.getState().rows).toEqual([])
  })

  it('marks success stale when completion hash differs', () => {
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
      currentYamlHash: 'h-changed',
    })
    expect(useGenericSimStore.getState().stale).toBe(true)
    expect(useGenericSimStore.getState().hasExportableResult('p1')).toBe(false)
    expect(useGenericSimStore.getState().hasDisplayResult('p1')).toBe(true)
  })

  it('uses YAML display_args (displayColumns) as default selected columns', () => {
    const columns = [
      '_cycle', '_consecutive_failures', '_safe_state',
      'pid2.MODE', 'pid2.MV', 'pid2.PV', 'pid2.SV',
      'source_flow', 'tank_1.level', 'tank_2.level',
      'valve_1.current_opening',
    ]
    const rows = [
      { _cycle: 0, 'tank_2.level': 0.1, 'pid2.SV': 0.8, 'pid2.MV': 0 },
      { _cycle: 1, 'tank_2.level': 0.5, 'pid2.SV': 0.8, 'pid2.MV': 55 },
    ]

    const epoch = useGenericSimStore.getState().epoch
    const runId = useGenericSimStore.getState().beginRun({
      projectId: 'p1',
      yamlHash: 'h1',
      cycles: 2,
      epoch,
    })
    useGenericSimStore.getState().succeed({
      projectId: 'p1',
      runId,
      epoch,
      columns,
      rows,
      completedCycles: rows.length,
      currentYamlHash: 'h1',
      // 引擎 get_display_variables 的顺序；not_a_column 应被过滤
      displayColumns: ['pid2.MV', 'pid2.PV', 'pid2.SV', 'pid2.MODE', 'tank_1.level', 'tank_2.level', 'not_a_column'],
    })

    expect(useGenericSimStore.getState().selectedColumns).toEqual([
      'pid2.MV', 'pid2.PV', 'pid2.SV', 'pid2.MODE', 'tank_1.level', 'tank_2.level',
    ])
  })

  it('selects nothing by default when YAML declares no display_args', () => {
    const epoch = useGenericSimStore.getState().epoch
    const runId = useGenericSimStore.getState().beginRun({
      projectId: 'p1',
      yamlHash: 'h1',
      cycles: 1,
      epoch,
    })
    useGenericSimStore.getState().succeed({
      projectId: 'p1',
      runId,
      epoch,
      columns: ['_cycle', 'x', 'y'],
      rows: [{ _cycle: 0, x: 1, y: 2 }],
      completedCycles: 1,
      currentYamlHash: 'h1',
      displayColumns: [],
    })

    expect(useGenericSimStore.getState().selectedColumns).toEqual([])
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
      currentYamlHash: 'h1',
    })
    useGenericSimStore.getState().markStale()
    expect(useGenericSimStore.getState().stale).toBe(true)
    expect(useGenericSimStore.getState().hasExportableResult('p1')).toBe(false)
    expect(useGenericSimStore.getState().hasDisplayResult('p1')).toBe(true)
  })
})
