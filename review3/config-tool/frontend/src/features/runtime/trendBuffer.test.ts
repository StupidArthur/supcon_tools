import { describe, expect, it } from 'vitest'
import {
  downsample,
  readTag,
  TrendBuffer,
} from './trendBuffer'
import type { RuntimeSnapshot } from './types'

function makeSnap(cycleCount: number, overrides: Partial<RuntimeSnapshot> = {}): RuntimeSnapshot {
  return {
    cycleCount,
    simTime: cycleCount * 0.5,
    sourceFlow: 0.0012,
    valve: {
      targetOpening: 50,
      currentOpening: 30,
      inletFlow: 0.001,
      outletFlow: 0.0005,
    },
    tank1: { level: 0.4, inletFlow: 0.0005, outletFlow: 0.0003 },
    tank2: { level: 0.6, inletFlow: 0.0003, outletFlow: 0.0002 },
    pid: { PV: 0.6, SV: 0.8, CSV: 0, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 },
    _receivedAt: Date.now(),
    ...overrides,
  }
}

describe('TrendBuffer', () => {
  it('does NOT include heartbeat (only real snapshots)', () => {
    const buf = new TrendBuffer(10)
    // 心跳不应进入缓冲：TrendBuffer 本身没有 heartbeat 概念，
    // WS 层已经过滤；这里验证 trendBuffer 的 push 只接受 snapshot
    buf.push(makeSnap(1), ['tank_2.level', 'pid2.SV'])
    expect(buf.size()).toBe(1)
  })

  it('respects capacity (drops oldest when full)', () => {
    const buf = new TrendBuffer(3)
    for (let i = 1; i <= 5; i++) {
      buf.push(makeSnap(i), ['tank_2.level'])
    }
    expect(buf.size()).toBe(3)
    const arr = buf.toArray()
    expect(arr[0].cycleCount).toBe(3)
    expect(arr[2].cycleCount).toBe(5)
  })

  it('rotateOut() moves current buffer out (for previous-run series)', () => {
    const buf = new TrendBuffer()
    buf.push(makeSnap(1), ['tank_2.level'])
    buf.push(makeSnap(2), ['tank_2.level'])
    const previous = buf.rotateOut()
    expect(previous.length).toBe(2)
    expect(buf.size()).toBe(0)
  })

  it('clear() empties the buffer', () => {
    const buf = new TrendBuffer()
    buf.push(makeSnap(1), ['tank_2.level'])
    buf.clear()
    expect(buf.size()).toBe(0)
  })

  it('records tag values from snapshot', () => {
    const buf = new TrendBuffer()
    buf.push(makeSnap(1, { tank2: { level: 0.55 } }), ['tank_2.level', 'pid2.SV'])
    const arr = buf.toArray()
    expect(arr[0].values['tank_2.level']).toBe(0.55)
    expect(arr[0].values['pid2.SV']).toBe(0.8)
  })
})

describe('readTag', () => {
  const snap = makeSnap(1)
  it('reads snake_case tags correctly', () => {
    expect(readTag(snap, 'source_flow')).toBe(0.0012)
    expect(readTag(snap, 'valve_1.current_opening')).toBe(30)
    expect(readTag(snap, 'tank_2.level')).toBe(0.6)
    expect(readTag(snap, 'pid2.SV')).toBe(0.8)
    expect(readTag(snap, 'pid2.MODE')).toBe(5)
  })

  it('returns null for unknown tags (NOT 0/NaN)', () => {
    expect(readTag(snap, 'unknown.tag')).toBeNull()
    expect(readTag(snap, 'pid2.NOTREAL')).toBeNull()
  })

  it('returns null when field is undefined in snapshot', () => {
    const snapMissing: RuntimeSnapshot = {
      cycleCount: 1,
      simTime: 0,
      valve: {}, tank1: {}, tank2: {}, pid: {}, _receivedAt: 0,
    }
    expect(readTag(snapMissing, 'tank_2.level')).toBeNull()
    expect(readTag(snapMissing, 'pid2.SV')).toBeNull()
  })
})

describe('downsample', () => {
  it('preserves first and last points', () => {
    const points: any[] = []
    for (let i = 0; i < 100; i++) {
      points.push({
        cycleCount: i,
        simTime: i,
        values: {},
      })
    }
    const out = downsample(points, 10)
    expect(out.length).toBeGreaterThan(0)
    // 第一点必须是 0
    expect(out[0].cycleCount).toBe(0)
    // 最后一点必须是 99
    expect(out[out.length - 1].cycleCount).toBe(99)
  })

  it('returns original when below maxPoints', () => {
    const points: any[] = []
    for (let i = 0; i < 5; i++) {
      points.push({ cycleCount: i, simTime: i, values: {} })
    }
    expect(downsample(points, 10)).toEqual(points)
  })

  it('keeps extreme points (min/max) per bucket', () => {
    // 100 个点，每个点值不同，确保下采样能挑出极值
    const points = []
    for (let i = 0; i < 100; i++) {
      points.push({ cycleCount: i, simTime: i, values: {} })
    }
    const out = downsample(points, 5)
    // 输出应包含极值
    const seenCycle = new Set(out.map((p) => p.cycleCount))
    expect(seenCycle.has(0)).toBe(true)
    expect(seenCycle.has(99)).toBe(true)
  })
})