/**
 * 导出会话纯逻辑测试：快照冻结 + 身份校验 + 列清洗 + 元数据校验。
 */
import { describe, expect, it } from 'vitest'
import {
  countSampledRows,
  createExportSession,
  EXPORT_SESSION_INVALID_MESSAGE,
  sanitizeExportColumns,
  sessionNumericColumns,
  validateExportRowMetadata,
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

describe('sanitizeExportColumns', () => {
  it('filters internal columns, trims, deduplicates, preserves order', () => {
    expect(
      sanitizeExportColumns([
        '_cycle',
        'pid2.MV',
        '_sim_time',
        'pid2.PV',
        '',
        ' pid2.SV ',
        '_need_sample',
        'pid2.MV',
      ]),
    ).toEqual(['pid2.MV', 'pid2.PV', 'pid2.SV'])
  })

  it('preserves input order without sorting', () => {
    expect(sanitizeExportColumns(['z', 'a', 'm'])).toEqual(['z', 'a', 'm'])
  })
})

describe('validateExportRowMetadata', () => {
  it('returns null for valid metadata', () => {
    expect(
      validateExportRowMetadata([
        { _cycle: 0, _sim_time: 1000, _need_sample: true, 'pid2.PV': 0.8 },
      ]),
    ).toBeNull()
  })

  it('returns error for empty rows', () => {
    expect(validateExportRowMetadata([])).toBe('当前没有可导出的仿真结果')
  })

  it('returns error when _sim_time is missing', () => {
    expect(
      validateExportRowMetadata([{ _cycle: 0, _need_sample: true }]),
    ).toBe('当前结果缺少标准时间戳元数据，请重新运行仿真')
  })

  it('returns error when _sim_time is NaN', () => {
    expect(
      validateExportRowMetadata([{ _sim_time: NaN, _need_sample: true }]),
    ).toBe('当前结果缺少标准时间戳元数据，请重新运行仿真')
  })

  it('returns error when _sim_time is Infinity', () => {
    expect(
      validateExportRowMetadata([{ _sim_time: Infinity, _need_sample: true }]),
    ).toBe('当前结果缺少标准时间戳元数据，请重新运行仿真')
  })

  it('returns error when _need_sample is missing', () => {
    expect(
      validateExportRowMetadata([{ _sim_time: 1000 }]),
    ).toBe('当前结果缺少采样标记，请重新运行仿真')
  })

  it('returns error when no sampled rows', () => {
    expect(
      validateExportRowMetadata([{ _sim_time: 1000, _need_sample: false }]),
    ).toBe('当前结果没有可导出的采样数据')
  })
})

describe('countSampledRows', () => {
  it('counts rows with _need_sample === true', () => {
    expect(
      countSampledRows([
        { _need_sample: true },
        { _need_sample: false },
        { _need_sample: true },
      ]),
    ).toBe(2)
  })
})
