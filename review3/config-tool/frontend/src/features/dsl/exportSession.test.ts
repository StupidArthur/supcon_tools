/**
 * 导出会话纯逻辑测试：快照冻结 + 身份校验。
 */
import { describe, expect, it } from 'vitest'
import {
  createExportSession,
  EXPORT_SESSION_INVALID_MESSAGE,
  sessionNumericColumns,
  validateExportSession,
} from './exportSession'

function makeSource(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 'p1',
    boundRunId: 'r1',
    boundYamlHash: 'h1',
    columns: ['_cycle', 'a', 'b'],
    selectedColumns: ['a'],
    rows: [
      { _cycle: 0, a: 1, b: 2 },
      { _cycle: 1, a: 3, b: 4 },
    ] as Array<Record<string, unknown>>,
    ...overrides,
  }
}

const okCurrent = {
  projectId: 'p1',
  boundRunId: 'r1',
  boundYamlHash: 'h1',
  stale: false,
  hasDisplayResult: true,
}

describe('createExportSession', () => {
  it('freezes rows (snapshot, not a live reference)', () => {
    const src = makeSource()
    const session = createExportSession(src)!
    // 改动原始 rows 不影响会话快照
    src.rows[0].a = 999
    src.rows.push({ _cycle: 2, a: 5, b: 6 })
    expect(session.rows[0].a).toBe(1)
    expect(session.rows.length).toBe(2)
    expect(session.rowCount).toBe(2)
  })

  it('copies columns and selectedColumns', () => {
    const src = makeSource()
    const session = createExportSession(src)!
    src.columns.push('c')
    src.selectedColumns.push('b')
    expect(session.columns).toEqual(['_cycle', 'a', 'b'])
    expect(session.selectedColumns).toEqual(['a'])
  })

  it('returns null without a run identity', () => {
    expect(createExportSession(makeSource({ boundRunId: null }))).toBeNull()
    expect(createExportSession(makeSource({ boundYamlHash: null }))).toBeNull()
  })
})

describe('validateExportSession', () => {
  const session = createExportSession(makeSource())!

  it('passes when identity is unchanged (uses session.rows)', () => {
    expect(validateExportSession(session, okCurrent)).toBeNull()
  })

  it('rejects when runId changed', () => {
    expect(validateExportSession(session, { ...okCurrent, boundRunId: 'r2' })).toBe(EXPORT_SESSION_INVALID_MESSAGE)
  })

  it('rejects when projectId changed', () => {
    expect(validateExportSession(session, { ...okCurrent, projectId: 'p2' })).toBe(EXPORT_SESSION_INVALID_MESSAGE)
  })

  it('rejects when yamlHash changed', () => {
    expect(validateExportSession(session, { ...okCurrent, boundYamlHash: 'h2' })).toBe(EXPORT_SESSION_INVALID_MESSAGE)
  })

  it('rejects when stale', () => {
    expect(validateExportSession(session, { ...okCurrent, stale: true })).toBe(EXPORT_SESSION_INVALID_MESSAGE)
  })

  it('rejects when result no longer belongs to the project', () => {
    expect(validateExportSession(session, { ...okCurrent, hasDisplayResult: false })).toBe(
      EXPORT_SESSION_INVALID_MESSAGE,
    )
  })
})

describe('sessionNumericColumns', () => {
  it('derives from session.rows, excluding _cycle and _-prefixed internals', () => {
    const session = createExportSession(
      makeSource({
        columns: ['_cycle', '_internal', 'a', 'txt'],
        rows: [{ _cycle: 0, _internal: 0, a: 1, txt: 'x' }],
      }),
    )!
    expect(sessionNumericColumns(session)).toEqual(['a'])
  })
})
