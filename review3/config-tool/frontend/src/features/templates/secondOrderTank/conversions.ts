// 单位换算与基础派生计算。
// 所有公式都只依赖输入数值；不调用 store、不做 IO，便于纯函数测试。

export const G = 9.81 // m/s²

// m³/s → L/min
export function cubicMeterPerSecondToLiterPerMinute(value: number): number {
  return value * 60_000
}

// L/min → m³/s
export function literPerMinuteToCubicMeterPerSecond(value: number): number {
  return value / 60_000
}

// 出口面积 (m²) → 等效直径 (mm)
export function outletAreaToDiameterMm(area: number): number {
  return 2 * Math.sqrt(area / Math.PI) * 1_000
}

// 等效直径 (mm) → 出口面积 (m²)
export function diameterMmToOutletArea(diameterMm: number): number {
  const m = diameterMm / 1_000
  return Math.PI * m * m / 4
}

// 圆柱形水箱容量 (L)
export function tankVolumeLiters(height: number, radius: number): number {
  return Math.PI * radius * radius * height * 1_000
}

// 托里拆利公式：液位 h (m) 与出口流量 q (m³/s)
export function torricelliOutflow(area: number, level: number): number {
  return area * Math.sqrt(2 * G * Math.max(level, 0))
}

// 由 SV 与 Tank 2 出口面积求目标出口流量（m³/s）。
export function steadyOutflowForSV(
  outletArea2: number,
  sv: number,
): number {
  return torricelliOutflow(outletArea2, sv)
}

// 给定水源流量与阀门流量系数，求可达阀位百分数 (0-100)。
// 若 maxSupply <= 0，返回 NaN（供上层判断"不可达"）。
export function requiredValvePercent(
  requiredFlow: number,
  sourceFlow: number,
  flowCoefficient: number,
): number {
  const maxSupply = sourceFlow * flowCoefficient
  if (maxSupply <= 0) return Number.NaN
  return (requiredFlow / maxSupply) * 100
}

// 目标稳态下 Tank 1 的稳态液位 (m)。
// 若 q=0 返回 0。
export function tank1SteadyLevel(
  requiredFlow: number,
  outletArea1: number,
): number {
  if (requiredFlow <= 0 || outletArea1 <= 0) return 0
  const v = requiredFlow / outletArea1
  return (v * v) / (2 * G)
}