/**
 * Stage 7 prospective: downsample numerical fixture contracts.
 * Uses existing public downsample() from trendBuffer when present.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const fixtureDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../tools/stage_verification/fixtures/downsample',
)

describe('stage 7 downsample acceptance', () => {
  it('preserves first/last/extrema and stays ≤3000 with ordered time', async () => {
    const { downsample } = await import('../../src/features/runtime/trendBuffer')
    const fx = JSON.parse(readFileSync(path.join(fixtureDir, 'downsample_extrema.json'), 'utf-8'))
    const out = downsample(fx.points, fx.maxPoints)
    expect(out.length, 'STAGE7-DOWNSAMPLE-001').toBeLessThanOrEqual(3000)
    expect(out[0].cycleCount, 'STAGE7-DOWNSAMPLE-002').toBe(fx.expect.preserveFirstCycle)
    expect(out.at(-1)?.cycleCount, 'STAGE7-DOWNSAMPLE-003').toBe(fx.expect.preserveLastCycle)
    const times = out.map((p: { simTime: number | null }) => p.simTime).filter((t: number | null) => t != null)
    for (const need of fx.expect.mustIncludeSimTimes as number[]) {
      expect(times, `STAGE7-DOWNSAMPLE-004/005 include ${need}`).toContain(need)
    }
    for (let i = 1; i < times.length; i++) {
      expect(times[i]! >= times[i - 1]!, 'STAGE7-DOWNSAMPLE-006').toBe(true)
    }
  })

  it('does not rewrite small series', async () => {
    const { downsample } = await import('../../src/features/runtime/trendBuffer')
    const fx = JSON.parse(readFileSync(path.join(fixtureDir, 'downsample_small.json'), 'utf-8'))
    const out = downsample(fx.points, fx.maxPoints)
    expect(out.length, 'STAGE7-DOWNSAMPLE-007').toBe(fx.expect.unchangedLength)
  })

  it('handles duplicate time and missing simTime deterministically', async () => {
    const { downsample } = await import('../../src/features/runtime/trendBuffer')
    const fx = JSON.parse(
      readFileSync(path.join(fixtureDir, 'downsample_duplicate_time.json'), 'utf-8'),
    )
    const a = downsample(fx.points, fx.maxPoints)
    const b = downsample(fx.points, fx.maxPoints)
    expect(JSON.stringify(a), 'STAGE7-DOWNSAMPLE-008').toBe(JSON.stringify(b))
    const times = a.map((p: { simTime: number | null }) => p.simTime)
    const finite = times.filter((t: number | null): t is number => typeof t === 'number')
    for (let i = 1; i < finite.length; i++) {
      expect(finite[i]! >= finite[i - 1]!, 'STAGE7-DOWNSAMPLE-008 order').toBe(true)
    }
  })
})
