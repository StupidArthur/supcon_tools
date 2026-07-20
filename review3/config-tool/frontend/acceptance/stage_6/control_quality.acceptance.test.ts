/**
 * Stage 6 prospective: computeControlQuality numerical fixture contracts.
 * See CONTRACT_SURFACES.md — does not assert internal helper existence alone.
 */
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

const fixtureDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../tools/stage_verification/fixtures/quality',
)

function loadFixture(name: string): {
  samples: Array<Record<string, unknown>>
  options: Record<string, unknown>
  expect: Record<string, unknown>
} {
  const raw = JSON.parse(readFileSync(path.join(fixtureDir, name), 'utf-8'))
  const samples = (raw.samples as Array<Record<string, unknown>>).map((s) => ({
    ...s,
    pv: s.pv === 'NaN' ? Number.NaN : s.pv === 'Infinity' ? Number.POSITIVE_INFINITY : s.pv,
  }))
  return { samples, options: raw.options, expect: raw.expect }
}

async function loadQuality(contractId: string) {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'runtime', 'controlQuality')),
    contractId,
    'Public computeControlQuality(samples, options) with numeric fixture assertions.',
  )
}

describe('stage 6 control quality acceptance', () => {
  it('quality fixtures are present for prospective baseline', () => {
    const files = readdirSync(fixtureDir).filter((f) => f.endsWith('.json'))
    for (const required of [
      'quality_perfect_tracking.json',
      'quality_overshoot.json',
      'quality_settles_at_60s.json',
      'quality_not_settled_at_59s.json',
      'quality_irregular_sampling.json',
      'quality_missing_nonfinite.json',
      'quality_parameter_event.json',
      'quality_level_limit_hits.json',
    ]) {
      expect(files, `STAGE6-QUALITY-001 fixture ${required}`).toContain(required)
    }
  })

  it('perfect tracking → near-zero steady-state error', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-002')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, number | boolean | unknown>
    const fx = loadFixture('quality_perfect_tracking.json')
    const result = compute(fx.samples, fx.options)
    expect(Number(result.steadyStateError), 'STAGE6-QUALITY-002').toBeLessThanOrEqual(
      Number(fx.expect.steadyStateErrorMax),
    )
    expect(result.settled, 'STAGE6-QUALITY-002').toBe(true)
  })

  it('overshoot fixture yields correct overshoot magnitude', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-002')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, number>
    const fx = loadFixture('quality_overshoot.json')
    const result = compute(fx.samples, fx.options)
    expect(result.overshoot, 'STAGE6-QUALITY-002').toBeGreaterThanOrEqual(
      Number(fx.expect.overshootMin),
    )
  })

  it('59s inside band is not settled; 60s window settles', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-003')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, boolean | number>
    const notYet = loadFixture('quality_not_settled_at_59s.json')
    expect(compute(notYet.samples, notYet.options).settled, 'STAGE6-QUALITY-003').toBe(false)
    const settled = loadFixture('quality_settles_at_60s.json')
    const r = compute(settled.samples, settled.options)
    expect(r.settled, 'STAGE6-QUALITY-003').toBe(true)
  })

  it('irregular sampling integrates MV saturation by time not sample count', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-004')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, number>
    const fx = loadFixture('quality_irregular_sampling.json')
    const result = compute(fx.samples, fx.options)
    expect(result.mvSaturationTime, 'STAGE6-QUALITY-004').toBeCloseTo(
      Number(fx.expect.mvSaturationTimeApprox),
      0,
    )
  })

  it('NaN/Infinity do not produce NaN metrics', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-004')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, number>
    const fx = loadFixture('quality_missing_nonfinite.json')
    const result = compute(fx.samples, fx.options)
    for (const [key, value] of Object.entries(result)) {
      if (typeof value === 'number') {
        expect(Number.isFinite(value), `STAGE6-QUALITY-004: ${key} must be finite`).toBe(true)
      }
    }
    expect(Number(result.invalidSampleCount), 'STAGE6-QUALITY-004').toBeGreaterThanOrEqual(
      Number(fx.expect.invalidSampleCountMin),
    )
  })

  it('parameter event opens new segment and archives previous', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-005')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => { segments: unknown[]; archivedSegments?: unknown[] }
    const fx = loadFixture('quality_parameter_event.json')
    const result = compute(fx.samples, fx.options)
    const segCount = (result.segments?.length ?? 0) + (result.archivedSegments?.length ?? 0)
    expect(segCount, 'STAGE6-QUALITY-005').toBeGreaterThanOrEqual(2)
    expect(
      (result.archivedSegments?.length ?? 0) >= 1 || (result.segments?.length ?? 0) >= 2,
      'STAGE6-QUALITY-006: previous segment archived',
    ).toBe(true)
  })

  it('level limit hits count edge events not per-frame', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-003')
    const compute = mod.computeControlQuality as (
      samples: unknown,
      options?: unknown,
    ) => Record<string, number>
    const fx = loadFixture('quality_level_limit_hits.json')
    const result = compute(fx.samples, fx.options)
    expect(result.levelHighHits, 'STAGE6-QUALITY-003').toBe(Number(fx.expect.levelHighHits))
    expect(result.levelLowHits, 'STAGE6-QUALITY-003').toBe(Number(fx.expect.levelLowHits))
  })
})
