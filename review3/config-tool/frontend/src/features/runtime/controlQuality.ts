/**
 * 控制品质纯计算模块（阶段 6）。
 *
 * 约束：本文件不得使用任何相对路径 import（acceptance 以 file:// + @vite-ignore 加载）。
 * 仅导出可观察公共表面：QualitySample / QualityOptions / computeControlQuality。
 */

/** 默认误差带（|PV-SV|），秒级稳定判定用。 */
const DEFAULT_ERROR_BAND = 0.02

/** 默认稳定窗口长度（秒）：连续处于误差带内达到该时长才 settled。 */
const DEFAULT_STABLE_WINDOW_SECONDS = 60

/** 未提供 MV 上下限时不累计饱和时间；提供后按闭区间判定。 */
const DEFAULT_MV_LOW: number | undefined = undefined
const DEFAULT_MV_HIGH: number | undefined = undefined

/** 未结算时 settlingTime 的有限占位值（配合 settled=false 使用）。 */
const SETTLING_TIME_UNSETTLED = -1

/** 空输入 / 无有效数据时的稳态误差默认值。 */
const DEFAULT_STEADY_STATE_ERROR = 0

/** 判定 SV 阶跃方向时的最小变化量。 */
const SV_STEP_EPS = 1e-12

/**
 * 单个品质采样点。
 * pv/sv/mv 可为 null；非有限值在计算时计入 invalidSampleCount。
 */
export interface QualitySample {
  t: number
  pv: number | null
  sv: number | null
  mv: number | null
  level?: number | null
}

/**
 * 品质计算选项。
 * parameterEventAt / events 用于在参数 applied 时刻切开 segment。
 */
export interface QualityOptions {
  errorBand?: number
  stableWindowSeconds?: number
  mvLow?: number
  mvHigh?: number
  levelLow?: number
  levelHigh?: number
  events?: Array<Record<string, unknown>>
  /** fixture 用：在该时刻切开前后 segment */
  parameterEventAt?: number
}

/** 单段品质指标（顶层结果与 segments 元素共用字段）。 */
interface QualitySegmentMetrics {
  startTime: number
  endTime: number | null
  steadyStateError: number
  overshoot: number
  settled: boolean
  settlingTime: number
  mvSaturationTime: number
  levelHighHits: number
  levelLowHits: number
  invalidSampleCount: number
}

/**
 * 判断未知值是否为有限数字。
 */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/**
 * 将任意值规范为有限数；否则返回 fallback。
 */
function finiteOr(value: unknown, fallback: number): number {
  return isFiniteNumber(value) ? value : fallback
}

/**
 * 样本在 pv/sv/mv 维度是否有效（用于指标计算，不含 level）。
 */
function isSampleCoreValid(sample: QualitySample): boolean {
  return (
    isFiniteNumber(sample.t) &&
    isFiniteNumber(sample.pv) &&
    isFiniteNumber(sample.sv) &&
    isFiniteNumber(sample.mv)
  )
}

/**
 * 从 options.events / parameterEventAt 解析参数 applied 切开时刻。
 */
function resolveParameterEventAt(options?: QualityOptions): number | null {
  if (options == null) {
    return null
  }
  if (isFiniteNumber(options.parameterEventAt)) {
    return options.parameterEventAt
  }
  const events = options.events
  if (!Array.isArray(events)) {
    return null
  }
  for (const event of events) {
    if (event == null || typeof event !== 'object') {
      continue
    }
    const typeRaw = event.type ?? event.kind ?? event.eventType ?? ''
    const type = String(typeRaw).toLowerCase()
    const isParameterApplied =
      type === 'parameter_applied' ||
      (type.includes('parameter') && type.includes('applied')) ||
      type === 'applied'
    if (!isParameterApplied) {
      continue
    }
    const t = event.t ?? event.time ?? event.at ?? event.timestamp
    if (isFiniteNumber(t)) {
      return t
    }
    const asNumber = Number(t)
    if (Number.isFinite(asNumber)) {
      return asNumber
    }
  }
  return null
}

/**
 * 液位信号：优先 level，缺失则回退 pv。
 */
function resolveLevelValue(sample: QualitySample): number | null {
  if (sample.level !== undefined && sample.level !== null) {
    return isFiniteNumber(sample.level) ? sample.level : null
  }
  return isFiniteNumber(sample.pv) ? sample.pv : null
}

/**
 * 计算超调量：按有效给定（SV）方向。
 * - SV 阶跃上升（或 PV 自下趋近）：max(0, max(pv) - final_sv)
 * - SV 阶跃下降（或 PV 自上趋近）：max(0, final_sv - min(pv))
 */
function computeOvershoot(validSamples: QualitySample[]): number {
  if (validSamples.length === 0) {
    return 0
  }
  let maxPv = -Infinity
  let minPv = Infinity
  for (const sample of validSamples) {
    const pv = sample.pv as number
    if (pv > maxPv) {
      maxPv = pv
    }
    if (pv < minPv) {
      minPv = pv
    }
  }
  const firstSv = validSamples[0].sv as number
  const lastSv = validSamples[validSamples.length - 1].sv as number
  const firstPv = validSamples[0].pv as number

  if (lastSv > firstSv + SV_STEP_EPS) {
    return Math.max(0, maxPv - lastSv)
  }
  if (lastSv < firstSv - SV_STEP_EPS) {
    return Math.max(0, lastSv - minPv)
  }
  // SV 未变：用初始 PV 相对最终 SV 的方向推断响应方向
  if (firstPv < lastSv - SV_STEP_EPS) {
    return Math.max(0, maxPv - lastSv)
  }
  if (firstPv > lastSv + SV_STEP_EPS) {
    return Math.max(0, lastSv - minPv)
  }
  return Math.max(0, Math.max(maxPv - lastSv, lastSv - minPv))
}

/**
 * MV 饱和时间积分：对区间 [t_i, t_{i+1}]，若样本 i 饱和则累加 (t_{i+1}-t_i)。
 */
function computeMvSaturationTime(
  samples: QualitySample[],
  mvLow: number | undefined,
  mvHigh: number | undefined,
): number {
  if (mvLow === undefined && mvHigh === undefined) {
    return 0
  }
  let total = 0
  for (let i = 0; i < samples.length - 1; i += 1) {
    const current = samples[i]
    const next = samples[i + 1]
    if (!isFiniteNumber(current.t) || !isFiniteNumber(next.t)) {
      continue
    }
    const dt = next.t - current.t
    if (!(dt > 0)) {
      continue
    }
    if (!isFiniteNumber(current.mv)) {
      continue
    }
    const saturatedLow = mvLow !== undefined && current.mv <= mvLow
    const saturatedHigh = mvHigh !== undefined && current.mv >= mvHigh
    if (saturatedLow || saturatedHigh) {
      total += dt
    }
  }
  return total
}

/**
 * 液位高/低限边沿计数：进入超限区域计 1 次，持续超限不计。
 */
function computeLevelLimitHits(
  samples: QualitySample[],
  levelLow: number | undefined,
  levelHigh: number | undefined,
): { levelHighHits: number; levelLowHits: number } {
  let levelHighHits = 0
  let levelLowHits = 0
  let prevHigh = false
  let prevLow = false
  let hasPrev = false

  for (const sample of samples) {
    const level = resolveLevelValue(sample)
    if (level === null) {
      continue
    }
    const isHigh = levelHigh !== undefined && level > levelHigh
    const isLow = levelLow !== undefined && level < levelLow
    if (hasPrev) {
      if (isHigh && !prevHigh) {
        levelHighHits += 1
      }
      if (isLow && !prevLow) {
        levelLowHits += 1
      }
    } else {
      // 首个有效点：若已在超限区，计为一次进入
      if (isHigh) {
        levelHighHits += 1
      }
      if (isLow) {
        levelLowHits += 1
      }
    }
    prevHigh = isHigh
    prevLow = isLow
    hasPrev = true
  }

  return { levelHighHits, levelLowHits }
}

/**
 * 在有效样本序列上判定 settled / settlingTime，并计算稳态误差。
 *
 * settled：|pv-sv| 连续处于 errorBand 内的时间跨度 >= stableWindowSeconds（按时间差，非样本数）。
 * settlingTime：首次满足条件时的窗口结束时刻；未 settled 为 SETTLING_TIME_UNSETTLED。
 * steadyStateError：settled 时取稳定窗口内 |pv-sv| 的时间加权平均；否则取末值 |pv-sv|。
 */
function computeSettlingAndError(
  validSamples: QualitySample[],
  errorBand: number,
  stableWindowSeconds: number,
): { settled: boolean; settlingTime: number; steadyStateError: number } {
  if (validSamples.length === 0) {
    return {
      settled: false,
      settlingTime: SETTLING_TIME_UNSETTLED,
      steadyStateError: DEFAULT_STEADY_STATE_ERROR,
    }
  }

  const last = validSamples[validSamples.length - 1]
  const lastError = Math.abs((last.pv as number) - (last.sv as number))
  const fallbackError = finiteOr(lastError, DEFAULT_STEADY_STATE_ERROR)

  let bandStartIndex = -1
  let settled = false
  let settlingTime = SETTLING_TIME_UNSETTLED
  let settleWindowStartIndex = -1
  let settleWindowEndIndex = -1

  for (let i = 0; i < validSamples.length; i += 1) {
    const sample = validSamples[i]
    const err = Math.abs((sample.pv as number) - (sample.sv as number))
    const inBand = err <= errorBand
    if (inBand) {
      if (bandStartIndex < 0) {
        bandStartIndex = i
      }
      const span = (sample.t as number) - (validSamples[bandStartIndex].t as number)
      if (!settled && span >= stableWindowSeconds) {
        settled = true
        settlingTime = sample.t as number
        settleWindowStartIndex = bandStartIndex
        settleWindowEndIndex = i
      }
    } else {
      bandStartIndex = -1
    }
  }

  if (!settled) {
    return {
      settled: false,
      settlingTime: SETTLING_TIME_UNSETTLED,
      steadyStateError: fallbackError,
    }
  }

  // 稳定窗口内时间加权平均 |pv-sv|
  let weightedSum = 0
  let weightTotal = 0
  for (let i = settleWindowStartIndex; i < settleWindowEndIndex; i += 1) {
    const a = validSamples[i]
    const b = validSamples[i + 1]
    const dt = (b.t as number) - (a.t as number)
    if (!(dt > 0)) {
      continue
    }
    const err = Math.abs((a.pv as number) - (a.sv as number))
    weightedSum += err * dt
    weightTotal += dt
  }
  // 窗口末点：若仅有单点跨度刚好满足，用末点误差
  if (!(weightTotal > 0)) {
    const endSample = validSamples[settleWindowEndIndex]
    const endErr = Math.abs((endSample.pv as number) - (endSample.sv as number))
    return {
      settled: true,
      settlingTime,
      steadyStateError: finiteOr(endErr, DEFAULT_STEADY_STATE_ERROR),
    }
  }

  return {
    settled: true,
    settlingTime,
    steadyStateError: finiteOr(weightedSum / weightTotal, fallbackError),
  }
}

/**
 * 对一段样本计算全部段内指标。
 */
function computeSegmentMetrics(
  samples: QualitySample[],
  options: {
    errorBand: number
    stableWindowSeconds: number
    mvLow: number | undefined
    mvHigh: number | undefined
    levelLow: number | undefined
    levelHigh: number | undefined
  },
): QualitySegmentMetrics {
  let invalidSampleCount = 0
  const validSamples: QualitySample[] = []

  for (const sample of samples) {
    if (!isSampleCoreValid(sample)) {
      invalidSampleCount += 1
      continue
    }
    validSamples.push(sample)
  }

  const startTime =
    samples.length > 0 && isFiniteNumber(samples[0].t)
      ? samples[0].t
      : validSamples.length > 0
        ? (validSamples[0].t as number)
        : 0
  const lastSample = samples.length > 0 ? samples[samples.length - 1] : null
  const endTime =
    lastSample != null && isFiniteNumber(lastSample.t) ? lastSample.t : null

  const settling = computeSettlingAndError(
    validSamples,
    options.errorBand,
    options.stableWindowSeconds,
  )
  const overshoot = computeOvershoot(validSamples)
  const mvSaturationTime = computeMvSaturationTime(samples, options.mvLow, options.mvHigh)
  const levelHits = computeLevelLimitHits(samples, options.levelLow, options.levelHigh)

  return {
    startTime: finiteOr(startTime, 0),
    endTime: endTime == null ? null : finiteOr(endTime, startTime),
    steadyStateError: finiteOr(settling.steadyStateError, DEFAULT_STEADY_STATE_ERROR),
    overshoot: finiteOr(overshoot, 0),
    settled: settling.settled,
    settlingTime: finiteOr(settling.settlingTime, SETTLING_TIME_UNSETTLED),
    mvSaturationTime: finiteOr(mvSaturationTime, 0),
    levelHighHits: levelHits.levelHighHits,
    levelLowHits: levelHits.levelLowHits,
    invalidSampleCount,
  }
}

/**
 * 空输入默认结果：全部有限可显示，不抛异常。
 */
function emptyResult(): Record<string, unknown> {
  return {
    startTime: 0,
    endTime: null,
    steadyStateError: DEFAULT_STEADY_STATE_ERROR,
    overshoot: 0,
    settled: false,
    settlingTime: SETTLING_TIME_UNSETTLED,
    mvSaturationTime: 0,
    levelHighHits: 0,
    levelLowHits: 0,
    invalidSampleCount: 0,
    segments: [],
    archivedSegments: [],
  }
}

/**
 * 将段指标展开为可返回的普通对象。
 */
function segmentToRecord(segment: QualitySegmentMetrics): Record<string, unknown> {
  return {
    startTime: segment.startTime,
    endTime: segment.endTime,
    steadyStateError: segment.steadyStateError,
    overshoot: segment.overshoot,
    settled: segment.settled,
    settlingTime: segment.settlingTime,
    mvSaturationTime: segment.mvSaturationTime,
    levelHighHits: segment.levelHighHits,
    levelLowHits: segment.levelLowHits,
    invalidSampleCount: segment.invalidSampleCount,
  }
}

/**
 * 计算控制品质指标。
 *
 * @param samples 时序采样（按时间升序）
 * @param options 误差带、稳定窗口、MV/液位限、参数事件等
 * @returns 含 steadyStateError / overshoot / settled / settlingTime /
 *          mvSaturationTime / levelHighHits / levelLowHits /
 *          invalidSampleCount / segments / archivedSegments 的有限可显示结果
 */
export function computeControlQuality(
  samples: QualitySample[],
  options?: QualityOptions,
): Record<string, unknown> {
  if (!Array.isArray(samples) || samples.length === 0) {
    return emptyResult()
  }

  const errorBand = finiteOr(options?.errorBand, DEFAULT_ERROR_BAND)
  const stableWindowSeconds = finiteOr(
    options?.stableWindowSeconds,
    DEFAULT_STABLE_WINDOW_SECONDS,
  )
  const mvLow = isFiniteNumber(options?.mvLow) ? options!.mvLow : DEFAULT_MV_LOW
  const mvHigh = isFiniteNumber(options?.mvHigh) ? options!.mvHigh : DEFAULT_MV_HIGH
  const levelLow = isFiniteNumber(options?.levelLow) ? options!.levelLow : undefined
  const levelHigh = isFiniteNumber(options?.levelHigh) ? options!.levelHigh : undefined

  const metricOptions = {
    errorBand,
    stableWindowSeconds,
    mvLow,
    mvHigh,
    levelLow,
    levelHigh,
  }

  const splitAt = resolveParameterEventAt(options)

  if (splitAt != null) {
    const before: QualitySample[] = []
    const after: QualitySample[] = []
    for (const sample of samples) {
      const t = isFiniteNumber(sample.t) ? sample.t : Number.NaN
      if (Number.isFinite(t) && t < splitAt) {
        before.push(sample)
      } else {
        after.push(sample)
      }
    }
    // 保证切开后至少能形成两段可观察结果
    const archived =
      before.length > 0
        ? computeSegmentMetrics(before, metricOptions)
        : computeSegmentMetrics([], metricOptions)
    const current =
      after.length > 0
        ? computeSegmentMetrics(after, metricOptions)
        : computeSegmentMetrics([], metricOptions)

    const archivedRecord = segmentToRecord(archived)
    const currentRecord = segmentToRecord(current)

    return {
      ...currentRecord,
      // 顶层聚合：无效样本计数跨段求和，便于观察
      invalidSampleCount: archived.invalidSampleCount + current.invalidSampleCount,
      segments: [currentRecord],
      archivedSegments: [archivedRecord],
    }
  }

  const metrics = computeSegmentMetrics(samples, metricOptions)
  const record = segmentToRecord(metrics)
  return {
    ...record,
    segments: [record],
    archivedSegments: [],
  }
}
