/**
 * 导出格式参数与默认值（前后端共享）。
 *
 * 放在 lib/ 而不是 features/dsl/，避免基础 API 层反向依赖 feature 层、形成循环依赖。
 * 当前版本支持的格式：csv / xlsx。
 */

export type ExportFormat = 'csv' | 'xlsx'

export const DEFAULT_EXPORT_FORMAT: ExportFormat = 'xlsx'
