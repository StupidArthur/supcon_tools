/**
 * 导出会话（ExportSession）：打开导出对话框时，对当前仿真结果的身份与数据做不可变快照。
 *
 * 目的：避免「打开结果 A 的导出窗口 → 同一工程运行出结果 B → 最终导出 B」。
 * - rows / columns / selectedColumns 全部复制（rows 逐行浅复制），不再引用 Store 中可变数组；
 * - 对话框展示的行数、列、默认选项全部来自会话快照；
 * - 确认导出前用 validateExportSession 复查身份（projectId/runId/yamlHash/stale），
 *   任一不匹配即取消，不创建文件。
 */

import type { ExportFormat } from '../../lib/exportTypes'

export type { ExportFormat }

export interface ExportSession {
  projectId: string
  runId: string
  yamlHash: string
  columns: string[]
  selectedColumns: string[]
  rows: Array<Record<string, unknown>>
  rowCount: number
}

interface ExportSessionSource {
  projectId: string
  boundRunId: string | null
  boundYamlHash: string | null
  columns: string[]
  selectedColumns: string[]
  rows: Array<Record<string, unknown>>
}

/** 从当前结果创建不可变导出会话；无有效运行身份（runId/yamlHash 缺失）时返回 null。 */
export function createExportSession(src: ExportSessionSource): ExportSession | null {
  if (!src.boundRunId || !src.boundYamlHash) return null
  const rows = src.rows.map((row) => ({ ...row }))
  return {
    projectId: src.projectId,
    runId: src.boundRunId,
    yamlHash: src.boundYamlHash,
    columns: [...src.columns],
    selectedColumns: [...src.selectedColumns],
    rows,
    rowCount: rows.length,
  }
}

interface ExportSessionCurrent {
  projectId: string
  boundRunId: string | null
  boundYamlHash: string | null
  stale: boolean
  /** 当前结果是否仍属于当前工程（boundProjectId===projectId 且 success 且有行）。 */
  hasDisplayResult: boolean
}

export const EXPORT_SESSION_INVALID_MESSAGE = '仿真结果已变化，请重新打开导出窗口'

/** 导出前身份检查：任一不匹配返回错误信息；全部通过返回 null。 */
export function validateExportSession(session: ExportSession, current: ExportSessionCurrent): string | null {
  if (
    current.projectId !== session.projectId ||
    current.boundRunId !== session.runId ||
    current.boundYamlHash !== session.yamlHash ||
    current.stale ||
    !current.hasDisplayResult
  ) {
    return EXPORT_SESSION_INVALID_MESSAGE
  }
  return null
}

/** 列是否为数值列（前 50 行内存在有限数值即为是）。 */
export function isNumericColumn(rows: Array<Record<string, unknown>>, col: string): boolean {
  for (const row of rows.slice(0, 50)) {
    const v = row[col]
    if (typeof v === 'number' && Number.isFinite(v)) return true
  }
  return false
}

/** 会话内可供勾选的列：排除 _cycle 与 _ 前缀内部字段，仅保留数值列。 */
export function sessionNumericColumns(session: ExportSession): string[] {
  return session.columns.filter(
    (c) => c !== '_cycle' && !c.startsWith('_') && isNumericColumn(session.rows, c),
  )
}
