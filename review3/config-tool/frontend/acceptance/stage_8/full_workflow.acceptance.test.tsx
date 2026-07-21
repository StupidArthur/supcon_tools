/**
 * Stage 8 prospective: frontend E2E steps via dynamic import (implementation-passable).
 * Missing modules → STAGE8-E2E-* via importContractModule; no capabilityReady list.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it, vi } from 'vitest'
import { candidatesFor, frontendSrc, importContractModule } from '../prospectiveImport'

const scenarioPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../tools/stage_verification/fixtures/e2e/stage_8_scenario.json',
)

describe('stage 8 full workflow acceptance', () => {
  it('loads scenario STAGE8-E2E-001..029', () => {
    const scenario = JSON.parse(readFileSync(scenarioPath, 'utf-8')) as {
      steps: Array<{ id: string; action: string }>
    }
    expect(scenario.steps).toHaveLength(29)
    expect(scenario.steps[0].id).toBe('STAGE8-E2E-001')
    expect(scenario.steps[28].id).toBe('STAGE8-E2E-029')
  })

  it('opens template store defaults (STAGE8-E2E-002)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'useTemplateStore')),
      'STAGE8-E2E-002',
      'Public useTemplateStore must open template and expose defaults.',
    )
    expect(mod.useTemplateStore, 'STAGE8-E2E-002').toBeTypeOf('function')
  })

  it('select-all diagram objects surface (STAGE8-E2E-003)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'SecondOrderTankDiagram')),
      'STAGE8-E2E-003',
      'Public diagram must support selecting all P&ID objects.',
    )
    expect(mod.SecondOrderTankDiagram || mod.default, 'STAGE8-E2E-003').toBeTruthy()
  })

  it('inspector edits tank2 radius (STAGE8-E2E-004)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'SecondOrderTankInspector')),
      'STAGE8-E2E-004',
      'Inspector must allow editing Tank 2 radius.',
    )
    expect(mod.SecondOrderTankInspector || mod.default, 'STAGE8-E2E-004').toBeTruthy()
  })

  it('Unicode save-as adapter (STAGE8-E2E-005)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'saveAs')),
      'STAGE8-E2E-005',
      'Public saveAs adapter must accept Unicode paths.',
    )
    const saveAs = mod.saveAs as ((path: string) => Promise<unknown>) | undefined
    expect(saveAs, 'STAGE8-E2E-005').toBeTypeOf('function')
  })

  it('illegal SV blocks save/start (STAGE8-E2E-007)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'validation')),
      'STAGE8-E2E-007',
      'Public validation must block illegal SV before save/start.',
    )
    const validate = mod.validateBeforeSave as ((doc: Record<string, unknown>) => { ok: boolean }) | undefined
    expect(validate, 'STAGE8-E2E-007').toBeTypeOf('function')
    const result = validate!({ SV: Number.NaN })
    expect(result.ok, 'STAGE8-E2E-007').toBe(false)
  })

  it('PidFaceplate modes and write status (STAGE8-E2E-014 UI)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'PidFaceplate')),
      'STAGE8-E2E-014',
      'PidFaceplate AUTO/MAN/CAS and pending/applied/failed.',
    )
    const { render, screen } = await import('@testing-library/react')
    const PidFaceplate = mod.PidFaceplate as React.FC<Record<string, unknown>>
    render(
      <PidFaceplate
        mode="AUTO"
        values={{ PV: 0.5, SV: 0.8, CSV: 0.7, MV: 30, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 }}
        writeStatus="pending"
        onSubmit={vi.fn()}
      />,
    )
    expect(screen.getByTestId('faceplate-write-status').textContent?.toLowerCase()).toContain(
      'pending',
    )
  })

  it('trend and events (STAGE8-E2E-018)', async () => {
    await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'RuntimeTrendPanel')),
      'STAGE8-E2E-018',
      'RuntimeTrendPanel with events pending/applied/failed.',
    )
  })

  it('writeback (STAGE8-E2E-019)', async () => {
    await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'writeback')),
      'STAGE8-E2E-019',
      'Public writeback actions.',
    )
  })

  it('batch mutex progress failure export (STAGE8-E2E-022)', async () => {
    const mod = await importContractModule(
      candidatesFor(frontendSrc('features', 'templates', 'secondOrderTank', 'BatchPanel')),
      'STAGE8-E2E-022',
      'BatchPanel progress/failure/export; realtime Start blocked while batch running.',
    )
    const { render, screen } = await import('@testing-library/react')
    const BatchPanel = mod.BatchPanel as React.FC<Record<string, unknown>>
    render(
      <BatchPanel status="failed" error="exit 2" progress={0.2} resultPoints={[]} exportPath="" />,
    )
    expect(screen.getByTestId('batch-error').textContent).toContain('exit 2')
    expect(screen.queryByTestId('batch-empty-success-chart')).toBeNull()
  })
})
