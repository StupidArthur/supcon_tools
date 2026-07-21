import { describe, it, expect } from 'vitest'
import type { DraftConfig } from '../types'
import {
  blockingPrecheckIssues,
  configsEqual,
  diffPaths,
  isDraftConsistent,
  steadyStatePrecheck,
  validateConfig,
  warningsForConfig,
} from './validationRules'

const defaultCfg: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: {
    fullTravelTime: 12,
    initialOpening: 0,
    flowCoefficient: 1,
    minOpening: 0,
    maxOpening: 100,
  },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.10 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10,
    SV: 0.8, MV: 0,
    MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

describe('validateConfig', () => {
  it('default config has no errors', () => {
    expect(validateConfig(defaultCfg)).toEqual([])
  })

  it('cycleTime must be > 0', () => {
    const bad = { ...defaultCfg, cycleTime: -1 }
    const errs = validateConfig(bad)
    expect(errs.find((e) => e.path === 'cycleTime')).toBeDefined()
  })

  it('SV must not exceed tank2.height', () => {
    const bad: DraftConfig = {
      ...defaultCfg,
      pid: { ...defaultCfg.pid, SV: 2.0, SVH: 2.0 },
    }
    const errs = validateConfig(bad)
    expect(errs.find((e) => e.path === 'pid.SV')).toBeDefined()
    expect(errs.find((e) => e.path === 'pid.SVH')).toBeDefined()
  })

  it('MODE must be integer 1..8', () => {
    const errs = validateConfig({ ...defaultCfg, pid: { ...defaultCfg.pid, MODE: 9 } })
    expect(errs.find((e) => e.path === 'pid.MODE')).toBeDefined()
  })

  it('SWPN must be 0 or 1', () => {
    expect(validateConfig({ ...defaultCfg, pid: { ...defaultCfg.pid, SWPN: 2 } })
      .find((e) => e.path === 'pid.SWPN')).toBeDefined()
  })

  it('initialLevel must be in [0, height]', () => {
    const errs = validateConfig({
      ...defaultCfg,
      tank1: { ...defaultCfg.tank1, initialLevel: 1.3 },
    })
    expect(errs.find((e) => e.path === 'tank1.initialLevel')).toBeDefined()
  })

  it('enforces PID operation limits and engineering ranges', () => {
    const bad: DraftConfig = {
      ...defaultCfg,
      pid: {
        ...defaultCfg.pid,
        SV: 1.1,
        SVH: 1.0,
        MV: 90,
        MVH: 80,
        SVL: -0.1,
        MVL: -1,
      },
    }
    const paths = validateConfig(bad).map((e) => e.path)
    expect(paths).toContain('pid.SV')
    expect(paths).toContain('pid.MV')
    expect(paths).toContain('pid.SVL')
    expect(paths).toContain('pid.MVL')
  })

  it('validates valve travel time and opening bounds', () => {
    const bad: DraftConfig = {
      ...defaultCfg,
      valve: { ...defaultCfg.valve, fullTravelTime: -1, minOpening: -1, maxOpening: 101 },
    }
    const paths = validateConfig(bad).map((e) => e.path)
    expect(paths).toContain('valve.fullTravelTime')
    expect(paths).toContain('valve.minOpening')
    expect(paths).toContain('valve.maxOpening')
  })
})

describe('steadyStatePrecheck', () => {
  it('default case: reachable, valve ≈66%, tank1 ≈0.512m', () => {
    const r = steadyStatePrecheck(defaultCfg)
    expect(r.reachable).toBe(true)
    expect(r.requiredValvePercent).toBeGreaterThan(65)
    expect(r.requiredValvePercent).toBeLessThan(67)
    expect(r.tank1Level).toBeGreaterThan(0.50)
    expect(r.tank1Level).toBeLessThan(0.53)
  })

  it('unreachable when source * coeff < required flow (BLOCKING error)', () => {
    const r = steadyStatePrecheck({ ...defaultCfg, sourceFlow: 0.0001 })
    expect(r.reachable).toBe(false)
    const errs = blockingPrecheckIssues({ ...defaultCfg, sourceFlow: 0.0001 })
    expect(errs.some((e) => e.path === 'sourceFlow' && e.level === 'error')).toBe(true)
  })

  it('Tank 1 overflow becomes BLOCKING error, not warning', () => {
    const cfg: DraftConfig = {
      ...defaultCfg,
      tank1: { ...defaultCfg.tank1, height: 0.2, outletArea: 0.0001 },
    }
    const errs = blockingPrecheckIssues(cfg)
    expect(errs.some((e) => e.path === 'tank1.outletArea' && e.level === 'error')).toBe(true)
    // 警告列表应仅含低优先级 warning，不再含 tank1.outletArea 的 error。
    const warns = warningsForConfig(cfg)
    expect(warns.some((w) => w.path === 'tank1.outletArea')).toBe(false)
  })

  it('validateConfig propagates unreachable & overflow as blocking errors', () => {
    const errs1 = validateConfig({ ...defaultCfg, sourceFlow: 0.0001 })
    expect(errs1.some((e) => e.path === 'sourceFlow' && e.level === 'error')).toBe(true)

    const errs2 = validateConfig({
      ...defaultCfg,
      tank1: { ...defaultCfg.tank1, height: 0.2, outletArea: 0.0001 },
    })
    expect(errs2.some((e) => e.path === 'tank1.outletArea' && e.level === 'error')).toBe(true)
  })
})

describe('configsEqual & diffPaths', () => {
  it('equal configs report no diffs', () => {
    expect(diffPaths(defaultCfg, defaultCfg)).toEqual([])
    expect(configsEqual(defaultCfg, defaultCfg)).toBe(true)
  })

  it('detects path differences', () => {
    const next: DraftConfig = {
      ...defaultCfg,
      tank2: { ...defaultCfg.tank2, radius: 0.18 },
      pid: { ...defaultCfg.pid, PB: 40 },
    }
    const diffs = diffPaths(next, defaultCfg)
    expect(diffs).toContain('tank2.radius')
    expect(diffs).toContain('pid.PB')
  })

  it('isDraftConsistent reports equality and hash match', () => {
    const res = isDraftConsistent(defaultCfg, defaultCfg, 'abc', 'abc')
    expect(res.draftEqualsSaved).toBe(true)
    expect(res.savedEqualsRunning).toBe(true)
  })

  it('isDraftConsistent detects hash mismatch', () => {
    const res = isDraftConsistent(defaultCfg, defaultCfg, 'abc', 'xyz')
    expect(res.draftEqualsSaved).toBe(true)
    expect(res.savedEqualsRunning).toBe(false)
  })

  it('null configs are not equal', () => {
    expect(configsEqual(null, defaultCfg)).toBe(false)
    expect(configsEqual(defaultCfg, null)).toBe(false)
  })
})
