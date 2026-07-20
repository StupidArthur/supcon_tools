/**
 * Stage 4 reviewer acceptance: P&ID reads runtime snapshot vs draft by mode.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { SecondOrderTankDiagram } from '../../src/features/templates/secondOrderTank/SecondOrderTankDiagram'
import { useTemplateStore } from '../../src/features/templates/useTemplateStore'
import { useRuntimeStore } from '../../src/features/runtime/useRuntimeStore'
import type { DraftConfig, TemplateRuntimeState } from '../../src/features/templates/types'
import type { ConnectionState } from '../../src/features/runtime/types'

const baseDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: {
    fullTravelTime: 12,
    initialOpening: 50,
    flowCoefficient: 1,
    minOpening: 0,
    maxOpening: 100,
  },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

function runningSnapshot() {
  return {
    cycleCount: 10,
    simTime: 5,
    sourceFlow: 0.002,
    valve: { currentOpening: 33, targetOpening: 40 },
    tank1: { level: 0.2 },
    tank2: { level: 0.55 },
    pid: { SV: 0.3, MODE: 4 },
    _receivedAt: Date.now(),
  }
}

function setRunning(
  state: TemplateRuntimeState,
  connection: ConnectionState,
  snap = runningSnapshot(),
  stale = false,
) {
  useTemplateStore.setState({
    runtimeState: state,
    runningConfig: structuredClone(baseDraft),
  })
  useRuntimeStore.setState({
    connectionState: connection,
    stale,
    latestSnapshot: snap,
  })
}

describe('stage 4 runtime diagram acceptance', () => {
  beforeEach(() => {
    useTemplateStore.getState().reset()
    useRuntimeStore.getState()._reset()
  })

  afterEach(() => {
    cleanup()
    useTemplateStore.getState().reset()
    useRuntimeStore.getState()._reset()
  })

  it('stopped state uses draft initialOpening for valve label', () => {
    const { container } = render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    expect(container.textContent).toContain('50.0%')
    expect(container.textContent).toContain('当前为组态预览，不是实时值')
  })

  it('running state uses valve current_opening not target_opening', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    const valveText = screen.getByTestId('valve-current-opening')
    expect(valveText.textContent).toBe('33.0%')
    expect(valveText.textContent).not.toContain('40')
  })

  it('running state uses snapshot tank level not draft initialLevel', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    const tank2Text = screen.getByTestId('tank_2-level-text')
    expect(tank2Text.textContent).toBe('0.550 m')
    expect(tank2Text.textContent).not.toContain('0.100')
  })

  it('missing snapshot fields show dash instead of draft fallback', () => {
    setRunning('SIMULATION_RUNNING', 'connected', {
      cycleCount: 1,
      simTime: 0.5,
      valve: {},
      tank1: {},
      tank2: {},
      pid: {},
      _receivedAt: Date.now(),
    })
    const { container } = render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    expect(container.textContent).toContain('—')
    expect(container.textContent).not.toContain('72.0 L/min')
  })

  it('stale running data renders dashed display without draft fallback', () => {
    setRunning('SIMULATION_RUNNING', 'connected', runningSnapshot(), true)
    const { container } = render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    expect(container.textContent).toContain('数据已过期')
  })
})
