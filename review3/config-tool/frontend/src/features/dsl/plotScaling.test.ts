/**
 * 绘图缩放纯逻辑测试（scalePlotValue / hasPlotScale）。
 *
 * 公式：plotValue = raw × 100 / scaleRef
 * 边界：scaleRef 缺失 / 非有限 / ≤ 0 → 返回原值；超过量程不截断。
 */
import { describe, expect, it } from 'vitest'
import { hasPlotScale, scalePlotValue } from './plotScaling'

describe('scalePlotValue', () => {
  it('applies ref scaling', () => {
    expect(scalePlotValue(0.8, 1.2)).toBeCloseTo(66.6667, 4)
    expect(scalePlotValue(66, 100)).toBe(66)
    expect(scalePlotValue(0.5, 1.2)).toBeCloseTo(41.6667, 4)
  })

  it('allows over-range values without clipping', () => {
    expect(scalePlotValue(1.32, 1.2)).toBe(110) // 故意超过 100
  })

  it('returns the raw value when ref is invalid', () => {
    expect(scalePlotValue(5, undefined)).toBe(5)
    expect(scalePlotValue(5, 0)).toBe(5)
    expect(scalePlotValue(5, -1)).toBe(5)
    expect(scalePlotValue(5, Number.NaN)).toBe(5)
    expect(scalePlotValue(5, Number.POSITIVE_INFINITY)).toBe(5)
  })

  it('returns the raw value when raw is not finite', () => {
    expect(scalePlotValue(Number.NaN, 1.2)).toBeNaN()
    expect(scalePlotValue(Number.POSITIVE_INFINITY, 1.2)).toBe(Number.POSITIVE_INFINITY)
  })
})

describe('hasPlotScale', () => {
  it('reports whether a column has a usable ref', () => {
    const scales: Record<string, number> = { 'pid.PV': 1.2, 'pid.MV': 100 }
    expect(hasPlotScale(scales, 'pid.PV')).toBe(true)
    expect(hasPlotScale(scales, 'pid.MV')).toBe(true)
    expect(hasPlotScale(scales, 'pid.SV')).toBe(false)
    expect(hasPlotScale(undefined, 'pid.PV')).toBe(false)
  })
  it('rejects invalid stored values', () => {
    expect(hasPlotScale({ 'a': 0 }, 'a')).toBe(false)
    expect(hasPlotScale({ 'a': -1 }, 'a')).toBe(false)
    expect(hasPlotScale({ 'a': Number.NaN }, 'a')).toBe(false)
    expect(hasPlotScale({ 'a': Number.POSITIVE_INFINITY }, 'a')).toBe(false)
  })
})
