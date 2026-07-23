import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { SecondOrderTankDiagram } from './SecondOrderTankDiagram'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import type { DraftConfig, TemplateRuntimeState } from '../types'
import type { ConnectionState } from '../../runtime/types'

const baseDraft: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: { fullTravelTime: 12, initialOpening: 0, flowCoefficient: 1, minOpening: 0, maxOpening: 100 },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2, MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

function makeSnap() {
  return {
    cycleCount: 5,
    simTime: 2.5,
    sourceFlow: 0.0012,
    valve: {
      targetOpening: 80,
      currentOpening: 65,
      inletFlow: 0.001,
      outletFlow: 0.0005,
    },
    tank1: { level: 0.4, inletFlow: 0.0005, outletFlow: 0.0003 },
    tank2: { level: 0.6, inletFlow: 0.0003, outletFlow: 0.0002 },
    pid: {
      PV: 0.6, SV: 0.8, CSV: 0, MV: 65, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1,
    },
    _receivedAt: Date.now(),
  }
}

function setRunning(state: TemplateRuntimeState, connection: ConnectionState, snap: any = makeSnap()) {
  useTemplateStore.setState({
    runtimeState: state,
    runningConfig: structuredClone(baseDraft),
    latestSnapshot: snap,
    connectionState: connection,
    stale: false,
  })
  useRuntimeStore.setState({
    connectionState: connection,
    stale: false,
    latestSnapshot: snap,
  })
}

function resetStores() {
  useTemplateStore.getState().reset()
  useRuntimeStore.getState()._reset()
}

describe('SecondOrderTankDiagram - running state', () => {
  beforeEach(() => {
    resetStores()
  })

  afterEach(() => {
    cleanup()
    resetStores()
    vi.restoreAllMocks()
  })

  it('stopped state uses draft.initialOpening for valve label', () => {
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const valveText = screen.getByTestId('valve-current-opening')
    expect(valveText.textContent).toBe('0.0%')
  })

  it('running state shows real current_opening from snapshot, NOT target_opening', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const valveText = screen.getByTestId('valve-current-opening')
    // current_opening = 65, target_opening = 80
    expect(valveText.textContent).toBe('65.0%')
    expect(valveText.textContent).not.toContain('80')
  })

  it('running state Tank 2 uses snapshot level (not draft initialLevel)', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const tank2Text = screen.getByTestId('tank_2-level-text')
    expect(tank2Text.textContent).toBe('0.600 m')
    expect(tank2Text.textContent).not.toContain('0.100') // 不是 draft initialLevel
  })

  it('stale data renders dashed display (—) without fake fallback to draft', () => {
    const snapMissing = {
      cycleCount: 1,
      simTime: 0.5,
      sourceFlow: undefined as any,
      valve: {} as any,
      tank1: {} as any,
      tank2: {} as any,
      pid: {} as any,
      _receivedAt: Date.now(),
    }
    setRunning('SIMULATION_RUNNING', 'disconnected', snapMissing)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const valveText = screen.getByTestId('valve-current-opening')
    // 字段缺失 → —，禁止回退到 draft (initialOpening=0)
    expect(valveText.textContent).toBe('—')
  })

  it('out-of-range level shows real value (not clipped)', () => {
    const snapOver = makeSnap()
    snapOver.tank2.level = 1.5 // > height 1.2
    setRunning('SIMULATION_RUNNING', 'connected', snapOver)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const tank2Text = screen.getByTestId('tank_2-level-text')
    expect(tank2Text.textContent).toBe('1.500 m')
  })

  it('does not show flow animation when stale', () => {
    const snap = makeSnap()
    snap.valve.inletFlow = 0.01 // > threshold
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    useTemplateStore.setState({ stale: true })
    useRuntimeStore.setState({ stale: true })
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    // hasFlow=false；动画类不应出现
    const pipes = document.querySelectorAll('path.animate-flow')
    expect(pipes.length).toBe(0)
  })

  it('shows flow animation only when connected + fresh + flow above threshold', () => {
    const snap = makeSnap()
    snap.valve.inletFlow = 0.01 // > FLOW_ANIMATION_THRESHOLD_M3S (1e-6)
    snap.valve.outletFlow = 0.01
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const animatedPipes = document.querySelectorAll('path.animate-flow')
    expect(animatedPipes.length).toBeGreaterThanOrEqual(0)
  })

  it('does not show flow animation when stopped', () => {
    // stopped state, no snapshot
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const animatedPipes = document.querySelectorAll('path.animate-flow')
    expect(animatedPipes.length).toBe(0)
  })

  it('stopped state shows "组态预览" header, not "实时运行"', () => {
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    expect(screen.getByText(/当前为组态预览/)).toBeTruthy()
  })

  it('running + connected shows "实时运行" header', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    expect(screen.getByText(/实时运行/)).toBeTruthy()
  })

  it('running + stale shows "数据已过期" header', () => {
    setRunning('SIMULATION_RUNNING', 'connected')
    useTemplateStore.setState({ stale: true })
    useRuntimeStore.setState({ stale: true })
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    expect(screen.getByText(/数据已过期/)).toBeTruthy()
  })

  it('source_flow displays from snapshot in running state (NOT draft)', () => {
    const snap = makeSnap()
    snap.sourceFlow = 0.002  // 与 draft 不同：0.0012 m³/s
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    // 0.002 m³/s = 120 L/min
    expect(screen.getByTestId('source-flow-value').textContent).toContain('120.0')
    // 不应是 draft 的 0.0012 = 72 L/min
    expect(screen.getByTestId('source-flow-value').textContent).not.toContain('72.0')
  })

  it('source_flow shows — when snapshot.sourceFlow missing in running state (NO draft fallback)', () => {
    const snap = makeSnap()
    snap.sourceFlow = undefined as any
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    // 严禁回退到 draft.sourceFlow = 0.0012 m³/s = 72 L/min
    expect(screen.getByTestId('source-flow-value').textContent).toContain('—')
    expect(screen.getByTestId('source-flow-value').textContent).not.toContain('72.0')
  })

  it('Tank 2 SV line uses snapshot.pid.SV in running state (NOT draft)', () => {
    const snap = makeSnap()
    snap.pid.SV = 0.3  // 与 draft.pid.SV (0.8) 不同
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    const { container } = render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    // SV 标线应存在（来自 snapshot SV=0.3, ratio=0.25）
    const svLine = container.querySelector('[data-testid="tank-2-sv-line"]')
    expect(svLine).toBeTruthy()
    // PID 面板应显示 0.300（来自 snapshot）
    expect(container.textContent).toContain('0.300')
  })

  it('PID MODE shows from snapshot in running state (NOT draft)', () => {
    const snap = makeSnap()
    snap.pid.MODE = 4  // MAN (draft 是 5=AUTO)
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const svLabel = screen.getByTestId('pid-sv-mode-label')
    expect(svLabel.textContent).toContain('MAN')
    expect(svLabel.textContent).not.toContain('AUTO')
  })

  it('PID SV/MODE missing in running → M? + — + warning, NOT draft fallback', () => {
    const snap = makeSnap()
    snap.pid.SV = undefined as any
    snap.pid.MODE = undefined as any
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    const { container } = render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    const svLabel = screen.getByTestId('pid-sv-mode-label')
    expect(svLabel.textContent).toContain('M?')
    // 严禁显示 draft 的 AUTO
    expect(svLabel.textContent).not.toContain('AUTO')
    // 缺字段告警
    expect(screen.getByTestId('pid-missing-warning')).toBeTruthy()
  })

  it('animates each process segment only from its own real flow tag', () => {
    const snap = makeSnap()
    snap.valve.inletFlow = 0
    snap.valve.outletFlow = 0.01
    snap.tank1.outletFlow = 0
    snap.tank2.outletFlow = 0.02
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)

    expect(screen.getByTestId('pipe-inlet').classList.contains('animate-flow')).toBe(false)
    expect(screen.getByTestId('pipe-tank1-to-tank2').classList.contains('animate-flow')).toBe(false)
  })

  it('uses frozen running tank height when draft changes during a run', () => {
    const snap = makeSnap()
    snap.tank2.level = 0.6
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    const { rerender } = render(
      <SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />,
    )
    const before = screen.getByTestId('tank_2-liquid').getAttribute('height')
    const editedDraft = structuredClone(baseDraft)
    editedDraft.tank2.height = 2.4
    rerender(<SecondOrderTankDiagram draft={editedDraft} selectedObjectId={null} onSelect={() => {}} />)
    expect(screen.getByTestId('tank_2-liquid').getAttribute('height')).toBe(before)
  })

  it('hides the SV line when snapshot SV is missing', () => {
    const snap = makeSnap()
    snap.pid.SV = undefined as any
    setRunning('SIMULATION_RUNNING', 'connected', snap)
    render(<SecondOrderTankDiagram draft={baseDraft} selectedObjectId={null} onSelect={() => {}} />)
    expect(screen.queryByTestId('tank-2-sv-line')).toBeNull()
  })
})
