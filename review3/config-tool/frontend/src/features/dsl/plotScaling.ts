/**
 * 绘图缩放（display_args 中的 [ref]）。
 *
 * plotValue = rawValue × 100 / scaleRef
 *
 * 设计：
 *  - 必须防止除零和无效值：scaleRef 缺失 / 非有限 / ≤ 0 时直接返回原值；
 *  - 超过量程（raw > scaleRef）允许保留，结果可能 >100（不主动截断）；
 *  - 不修改原始 rows / session.rows / 导出数据；只在构造 chartData 时应用。
 */

export function scalePlotValue(
  rawValue: number,
  scaleRef: number | undefined,
): number {
  if (
    !Number.isFinite(rawValue) ||
    scaleRef === undefined ||
    !Number.isFinite(scaleRef) ||
    scaleRef <= 0
  ) {
    return rawValue
  }
  return (rawValue * 100) / scaleRef
}

/** 是否对应该列应用绘图缩放（存在且为有限正数）。 */
export function hasPlotScale(
  plotScales: Record<string, number> | undefined,
  col: string,
): boolean {
  const s = plotScales?.[col]
  return typeof s === 'number' && Number.isFinite(s) && s > 0
}
