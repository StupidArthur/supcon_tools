// 校验与稳态预检查。
// 输入 DraftConfig，输出 errors/warnings 数组；不做 IO。
import {
  G,
  requiredValvePercent,
  tank1SteadyLevel,
  torricelliOutflow,
} from './conversions'
import type { DraftConfig, ValidationIssue } from '../types'

const path = (k: string) => k

function finiteOrInf(v: number): boolean {
  return Number.isFinite(v)
}

function rangeViolation(
  field: string,
  value: number,
  min: number,
  max: number,
): ValidationIssue | null {
  if (!finiteOrInf(value)) {
    return { path: path(field), level: 'error', message: `${field} 必须是有限数` }
  }
  if (value < min || value > max) {
    return {
      path: path(field),
      level: 'error',
      message: `${field} 须在 [${min}, ${max}] 之间`,
    }
  }
  return null
}

// 合法性校验：基础范围与 NaN/Inf。
export function validateConfig(cfg: DraftConfig): ValidationIssue[] {
  const errors: ValidationIssue[] = []

  if (!finiteOrInf(cfg.cycleTime) || cfg.cycleTime <= 0) {
    errors.push({
      path: 'cycleTime',
      level: 'error',
      message: '控制周期必须 > 0',
    })
  }

  if (!finiteOrInf(cfg.sourceFlow) || cfg.sourceFlow < 0) {
    errors.push({
      path: 'sourceFlow',
      level: 'error',
      message: '水源流量必须 >= 0 且有限',
    })
  }

  // 阀门
  const valve = cfg.valve
  if (!finiteOrInf(valve.fullTravelTime) || valve.fullTravelTime < 0) {
    errors.push({
      path: 'valve.fullTravelTime',
      level: 'error',
      message: '阀门满行程时间必须 >= 0',
    })
  }
  if (!finiteOrInf(valve.minOpening) || valve.minOpening < 0 || valve.minOpening > 100) {
    errors.push({
      path: 'valve.minOpening',
      level: 'error',
      message: '阀门最小开度必须在 [0, 100] 内',
    })
  }
  if (!finiteOrInf(valve.maxOpening) || valve.maxOpening < 0 || valve.maxOpening > 100) {
    errors.push({
      path: 'valve.maxOpening',
      level: 'error',
      message: '阀门最大开度必须在 [0, 100] 内',
    })
  }
  if (finiteOrInf(valve.minOpening) && finiteOrInf(valve.maxOpening) && valve.minOpening >= valve.maxOpening) {
    errors.push({
      path: 'valve.minOpening',
      level: 'error',
      message: '阀门最小开度必须 < 最大开度',
    })
  }
  const initRange = rangeViolation(
    'valve.initialOpening',
    valve.initialOpening,
    valve.minOpening,
    valve.maxOpening,
  )
  if (initRange) errors.push(initRange)
  if (!finiteOrInf(valve.flowCoefficient) || valve.flowCoefficient < 0) {
    errors.push({
      path: 'valve.flowCoefficient',
      level: 'error',
      message: '阀门流量系数必须 >= 0',
    })
  }

  // 两个水箱
  errors.push(...validateTank('tank1', cfg.tank1))
  errors.push(...validateTank('tank2', cfg.tank2))

  // PID
  errors.push(...validatePID(cfg))

  // 阻塞稳态预检查：不可达目标流量 / Tank 1 预计溢流
  errors.push(...blockingPrecheckIssues(cfg))

  return errors
}

function validateTank(prefix: 'tank1' | 'tank2', t: { height: number; radius: number; outletArea: number; initialLevel: number }): ValidationIssue[] {
  const errs: ValidationIssue[] = []
  if (!finiteOrInf(t.height) || t.height <= 0) {
    errs.push({ path: `${prefix}.height`, level: 'error', message: '水箱高度必须 > 0' })
  }
  if (!finiteOrInf(t.radius) || t.radius <= 0) {
    errs.push({ path: `${prefix}.radius`, level: 'error', message: '水箱半径必须 > 0' })
  }
  if (!finiteOrInf(t.outletArea) || t.outletArea <= 0) {
    errs.push({ path: `${prefix}.outletArea`, level: 'error', message: '出口面积必须 > 0' })
  }
  if (!finiteOrInf(t.initialLevel) || t.initialLevel < 0 || t.initialLevel > t.height) {
    errs.push({
      path: `${prefix}.initialLevel`,
      level: 'error',
      message: '初始液位必须在 [0, height] 之间',
    })
  }
  return errs
}

function validatePID(cfg: DraftConfig): ValidationIssue[] {
  const errs: ValidationIssue[] = []
  const pid = cfg.pid
  if (!finiteOrInf(pid.PB) || pid.PB <= 0) {
    errs.push({ path: 'pid.PB', level: 'error', message: 'PB 必须 > 0' })
  }
  if (!finiteOrInf(pid.TI) || pid.TI < 0) {
    errs.push({ path: 'pid.TI', level: 'error', message: 'TI 必须 >= 0' })
  }
  if (!finiteOrInf(pid.TD) || pid.TD < 0) {
    errs.push({ path: 'pid.TD', level: 'error', message: 'TD 必须 >= 0' })
  }
  if (!finiteOrInf(pid.KD) || pid.KD <= 0) {
    errs.push({ path: 'pid.KD', level: 'error', message: 'KD 必须 > 0' })
  }
  if (!Number.isInteger(pid.MODE) || pid.MODE < 1 || pid.MODE > 8) {
    errs.push({ path: 'pid.MODE', level: 'error', message: 'MODE 必须是 1..8 的整数' })
  }
  if (pid.SWPN !== 0 && pid.SWPN !== 1) {
    errs.push({ path: 'pid.SWPN', level: 'error', message: 'SWPN 必须为 0 或 1' })
  }
  if (!finiteOrInf(pid.SVSCH) || !finiteOrInf(pid.SVSCL) || pid.SVSCH <= pid.SVSCL) {
    errs.push({ path: 'pid.SVSCH', level: 'error', message: 'SVSCH 必须 > SVSCL' })
  }
  if (!finiteOrInf(pid.SVH) || !finiteOrInf(pid.SVL) || pid.SVH < pid.SVL) {
    errs.push({ path: 'pid.SVH', level: 'error', message: 'SVH 必须 >= SVL' })
  }
  if (!finiteOrInf(pid.MVSCH) || !finiteOrInf(pid.MVSCL) || pid.MVSCH <= pid.MVSCL) {
    errs.push({ path: 'pid.MVSCH', level: 'error', message: 'MVSCH 必须 > MVSCL' })
  }
  if (!finiteOrInf(pid.MVH) || !finiteOrInf(pid.MVL) || pid.MVH < pid.MVL) {
    errs.push({ path: 'pid.MVH', level: 'error', message: 'MVH 必须 >= MVL' })
  }
  if (!finiteOrInf(pid.SV) || pid.SV < pid.SVL || pid.SV > pid.SVH) {
    errs.push({ path: 'pid.SV', level: 'error', message: 'SV 必须在 [SVL, SVH] 内' })
  }
  if (!finiteOrInf(pid.MV) || pid.MV < pid.MVL || pid.MV > pid.MVH) {
    errs.push({ path: 'pid.MV', level: 'error', message: 'MV 必须在 [MVL, MVH] 内' })
  }
  if (finiteOrInf(pid.SVL) && finiteOrInf(pid.SVH) && finiteOrInf(pid.SVSCL) && finiteOrInf(pid.SVSCH) &&
      (pid.SVL < pid.SVSCL || pid.SVH > pid.SVSCH)) {
    errs.push({ path: 'pid.SVL', level: 'error', message: 'SVL/SVH 必须位于工程量程内' })
  }
  if (finiteOrInf(pid.MVL) && finiteOrInf(pid.MVH) && finiteOrInf(pid.MVSCL) && finiteOrInf(pid.MVSCH) &&
      (pid.MVL < pid.MVSCL || pid.MVH > pid.MVSCH)) {
    errs.push({ path: 'pid.MVL', level: 'error', message: 'MVL/MVH 必须位于工程量程内' })
  }
  // SV 与 Tank 2 高度联动：SVH <= tank2.height 时不允许 SV 越过 height。
  if (pid.SVH > cfg.tank2.height) {
    errs.push({
      path: 'pid.SVH',
      level: 'error',
      message: 'pid.SVH 不得超过 tank2.height',
    })
  }
  if (pid.SV > cfg.tank2.height) {
    errs.push({
      path: 'pid.SV',
      level: 'error',
      message: 'pid.SV 不得超过 tank2.height',
    })
  }
  return errs
}

// 稳态预检查：返回值用于 UI 提示。
//
// 阻塞错误（来自后端 ValidateTemplateConfig）：不可达目标流量、Tank 1 预计溢流。
// 警告（不阻塞保存）：阀位过低/过高、Tank 1 接近高度。
//
// 这里保留阻塞检查并以 ValidationIssue 形式输出，方便 store 与后端对齐。
export interface SteadyPrecheckResult {
  reachable: boolean
  tank1Level: number
  requiredValvePercent: number
  warnings: ValidationIssue[]
}

export function steadyStatePrecheck(cfg: DraftConfig): SteadyPrecheckResult {
  const warnings: ValidationIssue[] = []
  const q2 = torricelliOutflow(cfg.tank2.outletArea, cfg.pid.SV)
  const vp = requiredValvePercent(q2, cfg.sourceFlow, cfg.valve.flowCoefficient)
  const tank1Lvl = tank1SteadyLevel(q2, cfg.tank1.outletArea)

  const reachable = Number.isFinite(vp) && vp <= 100
  if (!reachable) {
    // 阻塞错误：目标稳态流量超过水源最大供给
    warnings.push({
      path: 'sourceFlow',
      level: 'error',
      message: '目标稳态流量超过水源最大供给',
    })
  }
  if (Number.isFinite(vp)) {
    if (vp < 5) {
      warnings.push({
        path: 'valve.flowCoefficient',
        level: 'warning',
        message: `预计阀位 ${vp.toFixed(1)}% 过低（< 5%）`,
      })
    } else if (vp > 95) {
      warnings.push({
        path: 'valve.flowCoefficient',
        level: 'warning',
        message: `预计阀位 ${vp.toFixed(1)}% 过高（> 95%）`,
      })
    }
  }
  if (tank1Lvl > cfg.tank1.height) {
    // 阻塞错误：Tank 1 预计溢流
    warnings.push({
      path: 'tank1.outletArea',
      level: 'error',
      message: `预计 Tank 1 稳态液位 ${tank1Lvl.toFixed(3)}m 超过水箱高度`,
    })
  } else if (tank1Lvl > cfg.tank1.height * 0.9) {
    warnings.push({
      path: 'tank1.outletArea',
      level: 'warning',
      message: `预计 Tank 1 稳态液位 ${tank1Lvl.toFixed(3)}m 接近水箱高度`,
    })
  }
  return {
    reachable,
    tank1Level: tank1Lvl,
    requiredValvePercent: Number.isFinite(vp) ? vp : Number.NaN,
    warnings,
  }
}

// warningsForConfig 把稳态检查中的非阻塞 warning 抽出来。
// 阻塞错误由 validateConfig 收集到 errors 列表中。
export function warningsForConfig(cfg: DraftConfig): ValidationIssue[] {
  return steadyStatePrecheck(cfg).warnings.filter((w) => w.level === 'warning')
}

// blockingPrecheckIssues 返回稳态检查中的阻塞错误（不可达 / 溢流）。
export function blockingPrecheckIssues(cfg: DraftConfig): ValidationIssue[] {
  return steadyStatePrecheck(cfg).warnings.filter((w) => w.level === 'error')
}

// draft / saved / running 三态一致性。
// 返回 true 表示三者完全一致（draft 与 saved 字段相同、saved 与 running hash 一致）。
export function isDraftConsistent(
  draft: DraftConfig | null,
  saved: DraftConfig | null,
  runningHash: string | null,
  savedHash: string | null,
): { draftEqualsSaved: boolean; savedEqualsRunning: boolean } {
  const draftEqualsSaved = configsEqual(draft, saved)
  const savedEqualsRunning =
    !!runningHash && !!savedHash && runningHash === savedHash
  return { draftEqualsSaved, savedEqualsRunning }
}

export function configsEqual(a: DraftConfig | null, b: DraftConfig | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  if (a.cycleTime !== b.cycleTime) return false
  if (a.clockMode !== b.clockMode) return false
  if (a.sourceFlow !== b.sourceFlow) return false
  for (const k of ['fullTravelTime', 'initialOpening', 'flowCoefficient', 'minOpening', 'maxOpening'] as const) {
    if (a.valve[k] !== b.valve[k]) return false
  }
  for (const k of ['height', 'radius', 'outletArea', 'initialLevel'] as const) {
    if (a.tank1[k] !== b.tank1[k]) return false
    if (a.tank2[k] !== b.tank2[k]) return false
  }
  for (const k of [
    'PB', 'TI', 'TD', 'KD', 'SV', 'MV',
    'MODE', 'SWPN',
    'SVSCL', 'SVSCH', 'SVL', 'SVH',
    'MVSCL', 'MVSCH', 'MVL', 'MVH',
  ] as const) {
    if (a.pid[k] !== b.pid[k]) return false
  }
  return true
}

// 列出两个配置之间的差异路径；用于 dirtyPaths 自动更新。
export function diffPaths(a: DraftConfig | null, b: DraftConfig | null): string[] {
  if (!a || !b) return []
  const paths: string[] = []
  if (a.cycleTime !== b.cycleTime) paths.push('cycleTime')
  if (a.clockMode !== b.clockMode) paths.push('clockMode')
  if (a.sourceFlow !== b.sourceFlow) paths.push('sourceFlow')
  for (const k of ['fullTravelTime', 'initialOpening', 'flowCoefficient', 'minOpening', 'maxOpening'] as const) {
    if (a.valve[k] !== b.valve[k]) paths.push(`valve.${k}`)
  }
  for (const k of ['height', 'radius', 'outletArea', 'initialLevel'] as const) {
    if (a.tank1[k] !== b.tank1[k]) paths.push(`tank1.${k}`)
    if (a.tank2[k] !== b.tank2[k]) paths.push(`tank2.${k}`)
  }
  for (const k of [
    'PB', 'TI', 'TD', 'KD', 'SV', 'MV',
    'MODE', 'SWPN',
    'SVSCL', 'SVSCH', 'SVL', 'SVH',
    'MVSCL', 'MVSCH', 'MVL', 'MVH',
  ] as const) {
    if (a.pid[k] !== b.pid[k]) paths.push(`pid.${k}`)
  }
  return paths
}

export { G }
