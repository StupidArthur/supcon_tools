/**
 * Stage 8 prospective: frontend walks scenario steps and fails per STAGE8-E2E-NNN.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const scenarioPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../tools/stage_verification/fixtures/e2e/stage_8_scenario.json',
)

describe('stage 8 full workflow acceptance', () => {
  it('loads scenario and reports each missing capability with stable IDs', () => {
    const scenario = JSON.parse(readFileSync(scenarioPath, 'utf-8')) as {
      steps: Array<{ id: string; action: string }>
    }
    expect(scenario.steps).toHaveLength(29)

    const capabilityReady: Record<string, boolean> = {
      // Only fixture/load itself is ready in prospective frontend harness.
      'STAGE8-E2E-001': true,
    }

    const failures: string[] = []
    for (const step of scenario.steps) {
      if (!capabilityReady[step.id]) {
        failures.push(`${step.id}: capability not ready for action ${step.action}`)
      }
    }
    expect(failures.length, 'prospective gaps expected').toBeGreaterThan(0)
    // Force a clear multi-id failure message for reviewers.
    expect.fail(failures.join('\n'))
  })
})
