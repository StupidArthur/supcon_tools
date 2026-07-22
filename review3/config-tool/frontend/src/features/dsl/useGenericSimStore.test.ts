/**
 * Unit tests for generic offline simulation store.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useGenericSimStore } from './useGenericSimStore'

describe('useGenericSimStore', () => {
  beforeEach(() => {
    useGenericSimStore.getState().clearResults()
    useGenericSimStore.getState().setCycles(2000)
  })

  it('tracks offline run lifecycle without template fields', () => {
    const store = useGenericSimStore.getState()
    store.beginRun(100)
    expect(useGenericSimStore.getState().status).toBe('running')
    expect(useGenericSimStore.getState().isRunning()).toBe(true)

    store.succeed({
      columns: ['_cycle', 'level', 'name'],
      rows: [
        { _cycle: 0, level: 1.2, name: 'a' },
        { _cycle: 1, level: 1.3, name: 'b' },
      ],
      completedCycles: 2,
    })
    const next = useGenericSimStore.getState()
    expect(next.status).toBe('success')
    expect(next.hasResult()).toBe(true)
    expect(next.completedCycles).toBe(2)
    expect(next.selectedColumns).toContain('level')
    expect(next.selectedColumns).not.toContain('name')
  })

  it('records backend failure text', () => {
    useGenericSimStore.getState().beginRun(10)
    useGenericSimStore.getState().fail('DataFactory 运行失败: parse error')
    expect(useGenericSimStore.getState().status).toBe('failed')
    expect(useGenericSimStore.getState().error).toContain('parse error')
    expect(useGenericSimStore.getState().hasResult()).toBe(false)
  })
})
