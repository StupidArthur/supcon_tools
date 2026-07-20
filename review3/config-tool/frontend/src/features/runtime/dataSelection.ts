// dataSelection：单一数据源选择函数。
//
// 关键规则（与 design §11 / playbook 阶段 4 一致）：
//   - 停止/组态状态使用 draft 初值。
//   - 运行状态使用 latestSnapshot。
//   - 缺失字段显示 `—` 与告警；禁止回退到 draft 冒充实时值。
//   - Tank 液位填充按 `level/height` 裁剪到 [0, 1]；越界仍显示真实数值 + 告警。
//   - 阀门必须使用 `valve_1.current_opening`，禁止用 target_opening 冒充实际阀位。
//   - 过程流动动画只有真实流量大于阈值且 snapshot 新鲜时才启用。

import type { DraftConfig, TemplateRuntimeState } from '../templates/types'
import type { ConnectionState, RuntimeNumber, RuntimeSnapshot } from './types'

// 与模板领域类型保持解耦：这里只用到它的形状。
// TemplateRuntimeState 是模板的状态机；运行时由 useRuntimeStore 透传。

export const FLOW_ANIMATION_THRESHOLD_M3S = 1e-6 // 1e-6 m³/s ≈ 0.06 L/min

export function isRuntimeRunning(state: TemplateRuntimeState): boolean {
  return state === 'SIMULATION_RUNNING' || state === 'REALTIME_RUNNING'
}

// selectRuntimeValue 的判定核心：决定现场图使用 draft 还是 latestSnapshot。
//   - 当 runtimeState 是运行态时：完全使用 snapshot；缺失字段返回 null。
//   - 当 runtimeState 是停止/组态态时：使用 draft 初值；缺失也返回 null。
// 该函数禁止回退（draft 冒充实时值）。
export interface DataSourceContext {
  runtimeState: TemplateRuntimeState
  latestSnapshot: RuntimeSnapshot | null
  draft: DraftConfig | null
  // 启动时冻结的配置；运行态几何量（如 tank height）只能从这里读取。
  runningConfig?: DraftConfig | null
}

// getRuntimeNumber 是单个字段的取值入口：返回 { value, present, finite }。
// 上层 UI 必须显式处理 `present=false` 的情况（显示 `—` + 告警）。
export function getRuntimeNumber(
  ctx: DataSourceContext,
  getter: (snap: RuntimeSnapshot) => number | undefined,
  draftGetter?: (draft: DraftConfig) => number | undefined,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  if (isRuntimeRunning(ctx.runtimeState)) {
    if (!ctx.latestSnapshot) {
      return { value: null, present: false, finite: false }
    }
    const raw = getter(ctx.latestSnapshot)
    if (raw === undefined || (typeof raw === 'number' && Number.isNaN(raw))) {
      return { value: null, present: false, finite: false }
    }
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      return { value: null, present: true, finite: false }
    }
    return { value: raw, present: true, finite: true }
  }
  // 停止/组态态：使用 draft 初值
  if (!ctx.draft || !draftGetter) {
    return { value: null, present: false, finite: false }
  }
  const raw = draftGetter(ctx.draft)
  if (raw === undefined || !Number.isFinite(raw as number)) {
    return { value: null, present: false, finite: false }
  }
  return { value: raw as number, present: true, finite: true }
}

// 单一数据源：Tank 液位（m）。返回原始数值 + 是否越界。
export function selectTankLevel(
  ctx: DataSourceContext,
  tank: 'tank1' | 'tank2',
): { level: RuntimeNumber; height: RuntimeNumber; ratio: RuntimeNumber; outOfRange: boolean } {
  const draftKey = tank === 'tank1' ? 'tank1' : 'tank2'
  const geometryConfig = isRuntimeRunning(ctx.runtimeState) ? ctx.runningConfig : ctx.draft
  const height = geometryConfig
    ? geometryConfig[draftKey].height
    : null

  let levelGetter: ((snap: RuntimeSnapshot) => number | undefined) | undefined
  let draftLevelGetter: ((d: DraftConfig) => number | undefined) | undefined

  if (tank === 'tank1') {
    levelGetter = (s) => s.tank1.level
    draftLevelGetter = (d) => d.tank1.initialLevel
  } else {
    levelGetter = (s) => s.tank2.level
    draftLevelGetter = (d) => d.tank2.initialLevel
  }

  const levelResult = getRuntimeNumber(ctx, levelGetter, draftLevelGetter)

  const ratio: RuntimeNumber =
    levelResult.value !== null && height !== null && height > 0
      ? levelResult.value / height
      : null

  const outOfRange = ratio !== null && (ratio < 0 || ratio > 1)

  // 裁剪到 [0, 1] 的 ratio 仅用于填充比例，数值本身仍返回原始 level。
  return { level: levelResult.value, height, ratio, outOfRange }
}

// 单一数据源：阀门实际开度（%）。必须用 current_opening，禁止 target_opening。
export function selectValveOpening(
  ctx: DataSourceContext,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  return getRuntimeNumber(
    ctx,
    (s) => s.valve.currentOpening,
    (d) => d.valve.initialOpening,
  )
}

// 单一数据源：阀门目标开度（%）。运行态用 snapshot.target_opening，停止态用 draft.initialOpening。
// 注意：与 selectValveOpening 严格分开，禁止用 target_opening 冒充实际阀位。
export function selectValveTargetOpening(
  ctx: DataSourceContext,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  return getRuntimeNumber(
    ctx,
    (s) => s.valve.targetOpening,
    (d) => d.valve.initialOpening,
  )
}

// 单一数据源：水源流量（m³/s）。运行态取 snapshot.source_flow，停止态取 draft.sourceFlow。
// 阶段 4 强制要求：运行态显示必须是 snapshot 的真实流量，禁止继续用 draft。
export function selectSourceFlow(
  ctx: DataSourceContext,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  return getRuntimeNumber(
    ctx,
    (s) => s.sourceFlow,
    (d) => d.sourceFlow,
  )
}

// 单一数据源：PID SV（m）。运行态取 snapshot.pid.SV，停止态取 draft.pid.SV。
export function selectPIDSetpoint(
  ctx: DataSourceContext,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  return getRuntimeNumber(
    ctx,
    (s) => s.pid.SV,
    (d) => d.pid.SV,
  )
}

// 单一数据源：PID MODE（1..8 整数）。运行态取 snapshot.pid.MODE，停止态取 draft.pid.MODE。
export function selectPIDMode(
  ctx: DataSourceContext,
): { value: RuntimeNumber; present: boolean; finite: boolean } {
  return getRuntimeNumber(
    ctx,
    (s) => s.pid.MODE,
    (d) => d.pid.MODE,
  )
}

// 单一数据源：过程流量（m³/s）。用于判断是否启用流动动画。
export type ProcessPipeId = 'inlet' | 'valveToTank1' | 'tank1ToTank2' | 'tank2Drain'

export function selectPipeFlow(ctx: DataSourceContext, pipe: ProcessPipeId): RuntimeNumber {
  if (pipe === 'inlet') {
    return getRuntimeNumber(
      ctx,
      (s) => s.valve.inletFlow,
      // 停止态没有真实流量；返回 NaN 让上层决定如何显示
      undefined,
    ).value
  }
  const getter = pipe === 'valveToTank1'
    ? (s: RuntimeSnapshot) => s.valve.outletFlow
    : pipe === 'tank1ToTank2'
      ? (s: RuntimeSnapshot) => s.tank1.outletFlow
      : (s: RuntimeSnapshot) => s.tank2.outletFlow
  return getRuntimeNumber(ctx, getter, undefined).value
}

// 过程流动动画开关：流量大于阈值且 snapshot 新鲜（连接状态为 connected 且未 stale）。
export function shouldShowFlowAnimation(
  ctx: DataSourceContext,
  connectionState: ConnectionState,
  stale: boolean,
  pipe: ProcessPipeId,
): boolean {
  if (!isRuntimeRunning(ctx.runtimeState)) return false
  if (connectionState !== 'connected') return false
  if (stale) return false
  const flow = selectPipeFlow(ctx, pipe)
  if (flow === null || !Number.isFinite(flow)) return false
  return flow > FLOW_ANIMATION_THRESHOLD_M3S
}

// 数值显示格式化：缺失或非有限 → `—`
export function formatRuntimeNumber(
  v: RuntimeNumber,
  digits = 3,
  unit = '',
): string {
  if (v === null) return '—'
  if (!Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}${unit ? ' ' + unit : ''}`
}

// stale 阈值计算：max(3 × cycleTime, 2s)。cycleTime 由 /api/status.cycle_time 提供。
export function computeStaleThresholdMs(cycleTime: number): number {
  const safe = Number.isFinite(cycleTime) && cycleTime > 0 ? cycleTime : 0.5
  return Math.max(safe * 3 * 1000, 2000)
}
