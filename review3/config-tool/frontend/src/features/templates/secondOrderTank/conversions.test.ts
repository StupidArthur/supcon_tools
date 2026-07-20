import { describe, it, expect } from 'vitest'
import {
  cubicMeterPerSecondToLiterPerMinute,
  literPerMinuteToCubicMeterPerSecond,
  outletAreaToDiameterMm,
  diameterMmToOutletArea,
  tankVolumeLiters,
  torricelliOutflow,
  requiredValvePercent,
  tank1SteadyLevel,
  G,
} from './conversions'

describe('unit conversions', () => {
  it('m³/s <-> L/min', () => {
    expect(cubicMeterPerSecondToLiterPerMinute(0.0012)).toBeCloseTo(72, 6)
    expect(literPerMinuteToCubicMeterPerSecond(72)).toBeCloseTo(0.0012, 9)
    expect(cubicMeterPerSecondToLiterPerMinute(0)).toBe(0)
  })

  it('outlet_area <-> diameter_mm', () => {
    // 直径约 17.84 mm => 面积 ~ 0.00025 m²
    const area = 0.00025
    const d = outletAreaToDiameterMm(area)
    expect(d).toBeCloseTo(17.84, 2)
    expect(diameterMmToOutletArea(d)).toBeCloseTo(area, 9)
  })

  it('tank volume ≈ 84.8 L for default config', () => {
    // π × 0.15² × 1.2 = 0.08482 m³ ≈ 84.823 L
    expect(tankVolumeLiters(1.2, 0.15)).toBeCloseTo(84.823, 3)
  })
})

describe('steady precheck formulas', () => {
  it('torricelliOutflow returns 0 for zero level', () => {
    expect(torricelliOutflow(0.0002, 0)).toBe(0)
  })

  it('torricelliOutflow matches sqrt(2 g h)', () => {
    const a = 0.0002
    const h = 0.8
    expect(torricelliOutflow(a, h)).toBeCloseTo(a * Math.sqrt(2 * G * h), 9)
  })

  it('requiredValvePercent returns NaN when sourceFlow * coeff <= 0', () => {
    expect(Number.isNaN(requiredValvePercent(1e-4, 0, 1))).toBe(true)
    expect(Number.isNaN(requiredValvePercent(1e-4, 0.0012, 0))).toBe(true)
  })

  it('default case yields ≈66% valve opening', () => {
    const q = torricelliOutflow(0.0002, 0.8)
    const vp = requiredValvePercent(q, 0.0012, 1.0)
    expect(vp).toBeGreaterThan(65)
    expect(vp).toBeLessThan(67) // 契约 6.3 允许 ±1% 容差
  })

  it('default case yields ≈0.512 m Tank 1 steady level', () => {
    const q = torricelliOutflow(0.0002, 0.8)
    const lvl = tank1SteadyLevel(q, 0.00025)
    expect(lvl).toBeGreaterThan(0.50)
    expect(lvl).toBeLessThan(0.53) // 契约 6.3 允许 ±0.01 m 容差
  })
})