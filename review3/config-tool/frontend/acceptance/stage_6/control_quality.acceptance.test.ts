/**
 * Stage 6 prospective acceptance: control quality pure-function contracts.
 */
import { describe, expect, it } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

async function loadQuality(contractId: string): Promise<Record<string, unknown>> {
  return importContractModule(
    candidatesFor(frontendSrc('features', 'runtime', 'controlQuality')),
    contractId,
    'Required metrics: error band, overshoot, steady-state error, settling time, 60s window, MV saturation, level limit hits, irregular intervals, missing/non-finite data, segment reset after parameter events.',
  )
}

describe('stage 6 control quality acceptance', () => {
  it('exports computeControlQuality', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-001')
    expect(mod.computeControlQuality, 'STAGE6-QUALITY-001').toBeTypeOf('function')
  })

  it('reports error band, overshoot, steady-state error, settling time', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-002')
    const compute = mod.computeControlQuality as (series: unknown) => Record<string, unknown>
    const result = compute([])
    for (const key of ['errorBand', 'overshoot', 'steadyStateError', 'settlingTime']) {
      expect(result, `STAGE6-QUALITY-002: missing ${key}`).toHaveProperty(key)
    }
  })

  it('uses 60 second stable window and tracks MV saturation + level limit hits', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-003')
    expect(mod.STABLE_WINDOW_SECONDS, 'STAGE6-QUALITY-003').toBe(60)
    const compute = mod.computeControlQuality as (series: unknown) => Record<string, unknown>
    const result = compute([])
    for (const key of ['mvSaturationTime', 'levelHighHits', 'levelLowHits']) {
      expect(result, `STAGE6-QUALITY-003: missing ${key}`).toHaveProperty(key)
    }
  })

  it('handles irregular intervals, missing data, and non-finite values', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-004')
    const compute = mod.computeControlQuality as (series: unknown) => Record<string, unknown>
    const result = compute([
      { simTime: 0, pv: 0.5, sv: 0.8, mv: 10 },
      { simTime: 1.7, pv: Number.NaN, sv: 0.8, mv: 10 },
      { simTime: 2.0, pv: Number.POSITIVE_INFINITY, sv: 0.8, mv: 100 },
    ])
    expect(result.invalidSampleCount, 'STAGE6-QUALITY-004').toBeGreaterThan(0)
  })

  it('resets current segment metrics after parameter events while archiving previous', async () => {
    const mod = await loadQuality('STAGE6-QUALITY-005')
    expect(mod.resetQualitySegment, 'STAGE6-QUALITY-005').toBeTypeOf('function')
    expect(mod.getArchivedSegments, 'STAGE6-QUALITY-006').toBeTypeOf('function')
  })
})
