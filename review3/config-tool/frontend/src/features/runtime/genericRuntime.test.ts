import { describe, expect, it } from 'vitest'
import { buildRuntimeFrame } from './types'
import { TrendBuffer } from './trendBuffer'

describe('buildRuntimeFrame', () => {
  it('puts arbitrary tags into values', () => {
    const frame = buildRuntimeFrame({ 'pid.PV': 0.5, 'boiler.temp': 99, cycle_count: 3, sim_time: 1.5 }, 1000)
    expect(frame.values['pid.PV']).toBe(0.5)
    expect(frame.values['boiler.temp']).toBe(99)
    expect(frame.cycleCount).toBe(3)
    expect(frame.simTime).toBe(1.5)
    expect(frame.receivedAt).toBe(1000)
  })

  it('excludes runtime metadata from values', () => {
    const frame = buildRuntimeFrame({ cycle_count: 1, sim_time: 0.5, 'pid.PV': 0.1, _heartbeat: true }, 1)
    expect(frame.values['cycle_count']).toBeUndefined()
    expect(frame.values['sim_time']).toBeUndefined()
    expect(frame.values['_heartbeat']).toBeUndefined()
    expect(frame.values['pid.PV']).toBe(0.1)
  })

  it('unknown tag value becomes null, not dropped', () => {
    const frame = buildRuntimeFrame({ 'x.y': { weird: 1 } as any }, 1)
    expect(frame.values['x.y']).toBeNull()
  })

  it('simTime=0 is preserved, not treated as missing', () => {
    const frame = buildRuntimeFrame({ sim_time: 0, cycle_count: 0 }, 1)
    expect(frame.simTime).toBe(0)
    expect(frame.cycleCount).toBe(0)
  })
})

describe('TrendBuffer.pushFrame', () => {
  it('reads frame.values[tag] directly', () => {
    const buf = new TrendBuffer()
    const frame = buildRuntimeFrame({ 'pid.PV': 0.7, sim_time: 2 }, 1)
    buf.pushFrame(frame, ['pid.PV'])
    const arr = buf.toArray()
    expect(arr).toHaveLength(1)
    expect(arr[0].values['pid.PV']).toBe(0.7)
    expect(arr[0].simTime).toBe(2)
  })

  it('missing value stays null', () => {
    const buf = new TrendBuffer()
    const frame = buildRuntimeFrame({ 'pid.PV': 0.7 }, 1)
    buf.pushFrame(frame, ['pid.PV', 'pid.SV'])
    const arr = buf.toArray()
    expect(arr[0].values['pid.SV']).toBeNull()
  })

  it('simTime=0 kept as 0 in point', () => {
    const buf = new TrendBuffer()
    const frame = buildRuntimeFrame({ sim_time: 0, 'a.b': 1 }, 1)
    buf.pushFrame(frame, ['a.b'])
    expect(buf.toArray()[0].simTime).toBe(0)
  })

  it('respects capacity', () => {
    const buf = new TrendBuffer(2)
    for (let i = 0; i < 5; i++) {
      buf.pushFrame(buildRuntimeFrame({ 'a.b': i, sim_time: i }, i), ['a.b'])
    }
    expect(buf.size()).toBe(2)
  })
})
