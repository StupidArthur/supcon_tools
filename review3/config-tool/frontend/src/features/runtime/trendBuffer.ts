// trendBuffer：环形缓冲用于趋势数据（阶段 4）。
//
// - 心跳不进入缓冲。
// - 仅保留真实 snapshot，最多 N 个；超出时丢弃最旧。
// - 取数应保持 FIFO 顺序。

import type { RuntimeFrame, RuntimeSnapshot } from './types'

export interface TrendPoint {
  // cycleCount/simTime 可以为 null：snapshot 缺字段时如实缺失，绝不替换为 0。
  cycleCount: number | null
  simTime: number | null
  values: Record<string, number | null>
}

export class TrendBuffer {
  private capacity: number
  private buffer: TrendPoint[] = []

  constructor(capacity = 1200) {
    this.capacity = Math.max(1, Math.floor(capacity))
  }

  setCapacity(c: number): void {
    this.capacity = Math.max(1, Math.floor(c))
    if (this.buffer.length > this.capacity) {
      this.buffer.splice(0, this.buffer.length - this.capacity)
    }
  }

  push(snap: RuntimeSnapshot, tags: string[]): void {
    const values: Record<string, number | null> = {}
    for (const tag of tags) {
      const v = readTag(snap, tag)
      values[tag] = v
    }
    this.buffer.push({
      // 缺失 cycleCount/simTime 时也保留为 null；trend 图层会用 null 跳过该点。
      cycleCount: snap.cycleCount ?? null,
      simTime: snap.simTime ?? null,
      values,
    })
    if (this.buffer.length > this.capacity) {
      this.buffer.splice(0, this.buffer.length - this.capacity)
    }
  }

  // 通用运行帧入口：直接读取 frame.values[tag]，不依赖固定字段映射。
  // 缺失或非有限值记为 null；simTime=0 是有效值，不被误判缺失。
  pushFrame(frame: RuntimeFrame, tags: string[]): void {
    const values: Record<string, number | null> = {}
    for (const tag of tags) {
      const v = frame.values[tag]
      values[tag] = typeof v === 'number' && Number.isFinite(v) ? v : null
    }
    this.buffer.push({
      cycleCount: frame.cycleCount ?? null,
      simTime: frame.simTime ?? null,
      values,
    })
    if (this.buffer.length > this.capacity) {
      this.buffer.splice(0, this.buffer.length - this.capacity)
    }
  }

  // 替换语义：把当前 buffer 移到 previousRunSeries；下一次 restart 仿真调用此方法。
  rotateOut(): TrendPoint[] {
    const out = this.buffer
    this.buffer = []
    return out
  }

  toArray(): TrendPoint[] {
    return [...this.buffer]
  }

  size(): number {
    return this.buffer.length
  }

  clear(): void {
    this.buffer = []
  }
}

// readTag：把 snapshot 的扁平 tag 路径（"tank_2.level"）映射到 camelCase 结构。
// 缺失字段返回 null；禁止返回 0/NaN 假装有值。
export function readTag(snap: RuntimeSnapshot, tag: string): number | null {
  switch (tag) {
    case 'source_flow':
      return finiteOrNull(snap.sourceFlow)
    case 'cycle_count':
      return snap.cycleCount !== undefined && Number.isFinite(snap.cycleCount)
        ? snap.cycleCount
        : null
    case 'sim_time':
      return snap.simTime !== undefined && Number.isFinite(snap.simTime)
        ? snap.simTime
        : null
    case 'valve_1.target_opening':
      return finiteOrNull(snap.valve.targetOpening)
    case 'valve_1.current_opening':
      return finiteOrNull(snap.valve.currentOpening)
    case 'valve_1.inlet_flow':
      return finiteOrNull(snap.valve.inletFlow)
    case 'valve_1.outlet_flow':
      return finiteOrNull(snap.valve.outletFlow)
    case 'tank_1.level':
      return finiteOrNull(snap.tank1.level)
    case 'tank_1.inlet_flow':
      return finiteOrNull(snap.tank1.inletFlow)
    case 'tank_1.outlet_flow':
      return finiteOrNull(snap.tank1.outletFlow)
    case 'tank_2.level':
      return finiteOrNull(snap.tank2.level)
    case 'tank_2.inlet_flow':
      return finiteOrNull(snap.tank2.inletFlow)
    case 'tank_2.outlet_flow':
      return finiteOrNull(snap.tank2.outletFlow)
    case 'pid2.PV':
      return finiteOrNull(snap.pid.PV)
    case 'pid2.SV':
      return finiteOrNull(snap.pid.SV)
    case 'pid2.CSV':
      return finiteOrNull(snap.pid.CSV)
    case 'pid2.MV':
      return finiteOrNull(snap.pid.MV)
    case 'pid2.PB':
      return finiteOrNull(snap.pid.PB)
    case 'pid2.TI':
      return finiteOrNull(snap.pid.TI)
    case 'pid2.TD':
      return finiteOrNull(snap.pid.TD)
    case 'pid2.KD':
      return finiteOrNull(snap.pid.KD)
    case 'pid2.MODE':
      return finiteOrNull(snap.pid.MODE)
    case 'pid2.SWPN':
      return finiteOrNull(snap.pid.SWPN)
    default:
      return null
  }
}

function finiteOrNull(v: number | undefined): number | null {
  if (v === undefined) return null
  if (!Number.isFinite(v)) return null
  return v
}

// 下采样：保留首尾和每个桶的局部最小最大值；上限 3000 点（阶段 7 大批量结果用）
export function downsample(points: TrendPoint[], maxPoints: number): TrendPoint[] {
  if (maxPoints <= 0 || points.length <= maxPoints) return points
  const n = points.length
  const bucketSize = n / maxPoints
  const out: TrendPoint[] = []
  for (let i = 0; i < maxPoints; i++) {
    const start = Math.floor(i * bucketSize)
    const end = Math.min(n, Math.floor((i + 1) * bucketSize))
    if (end <= start) continue
    out.push(points[start])
    if (end - start > 2) {
      let minIdx = start
      let maxIdx = start
      // 跳过 simTime=null 的点；如果桶里全 null，跳过本桶
      const s0 = points[start].simTime
      const s1 = points[end - 1].simTime
      if (s0 === null || s1 === null) continue
      let minVal = points[start].simTime as number
      let maxVal = points[start].simTime as number
      let minIdxReal = start
      let maxIdxReal = start
      for (let j = start + 1; j < end; j++) {
        const sj = points[j].simTime
        if (sj === null) continue
        if (sj < minVal) { minVal = sj; minIdxReal = j }
        if (sj > maxVal) { maxVal = sj; maxIdxReal = j }
      }
      if (minIdxReal !== start && minIdxReal !== end - 1) out.push(points[minIdxReal])
      if (maxIdxReal !== start && maxIdxReal !== end - 1) out.push(points[maxIdxReal])
    }
    if (end - 1 !== start) out.push(points[end - 1])
  }
  return out
}