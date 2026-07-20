import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, act } from '@testing-library/react'
import { SecondOrderTankInspector } from './SecondOrderTankInspector'
import { useTemplateStore } from '../useTemplateStore'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import type { DraftConfig } from '../types'
import type { ConnectionState, RuntimeSnapshot } from '../../runtime/types'

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

function makeSnap(level: number, opening: number, cycleCount = 1): RuntimeSnapshot {
  return {
    cycleCount,
    simTime: cycleCount * 0.5,
    sourceFlow: 0.0012,
    valve: {
      targetOpening: opening,
      currentOpening: opening,
      inletFlow: 0.001,
      outletFlow: 0.0005,
    },
    tank1: { level, inletFlow: 0.0005, outletFlow: 0.0003 },
    tank2: { level: 0.8, inletFlow: 0.0003, outletFlow: 0.0002 },
    pid: {
      PV: 0.8, SV: 0.8, CSV: 0, MV: opening, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1,
    },
    _receivedAt: Date.now(),
  }
}

function seedTemplateStore(runtimeState: 'STOPPED_EDITING' | 'SIMULATION_RUNNING' = 'SIMULATION_RUNNING') {
  useTemplateStore.setState({
    templateId: 'second_order_tank',
    definition: {
      id: 'second_order_tank',
      displayName: '单阀门二阶水箱',
      defaultBuiltinPath: 'config/单阀门二阶水箱.yaml',
      programs: [],
    },
    sourcePath: 'config/单阀门二阶水箱.yaml',
    saved: { ...structuredClone(baseDraft), path: 'config/单阀门二阶水箱.yaml', contentHash: 'h' },
    draft: structuredClone(baseDraft),
    savedContentHash: 'h',
    selectedObjectId: 'tank_2',
    dirtyPaths: new Set(),
    validationErrors: [],
    validationWarnings: [],
    latestSnapshot: null,
    snapshotReceivedAt: null,
    connectionState: 'idle',
    stale: false,
    cycleTime: 0.5,
    runtimeName: null,
    runtimeState,
    loadError: null,
    saveError: null,
    runningConfigIdentity: null,
    lastSavedPath: 'config/单阀门二阶水箱.yaml',
    lastSavedHash: 'h',
  })
  useRuntimeStore.getState()._reset()
}

describe('Inspector runtime tab - Zustand subscription reactivity', () => {
  beforeEach(() => {
    seedTemplateStore()
  })

  afterEach(() => {
    cleanup()
    useTemplateStore.getState().reset()
    useRuntimeStore.getState()._reset()
    vi.restoreAllMocks()
  })

  it('inspector subscribes via useRuntimeStore selector (no getState in render)', () => {
    // 这是组件契约测试：runtime store 更新必须直接触发 UI 自动刷新。
    useTemplateStore.setState({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: makeSnap(0.5, 30),
      snapshotReceivedAt: Date.now(),
      connectionState: 'connected',
      runtimeName: 'second_order_tank',
      cycleTime: 0.5,
      stale: false,
    })
    useRuntimeStore.setState({
      connectionState: 'connected',
      latestSnapshot: makeSnap(0.5, 30),
      cycleTime: 0.5,
      runtimeName: 'real_runtime_from_status',
    })

    render(<SecondOrderTankInspector
      selectedObjectId="tank_2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)

    // 切换到运行页签
    const runtimeTab = screen.getByTestId('tab-runtime')
    act(() => { runtimeTab.click() })

    // 初次渲染：tank_2.level = 0.8
    expect(screen.getByTestId('runtime-field-tank_2.level').textContent).toContain('0.800')

    // 关键：snapshot 更新必须自动触发 UI 重渲染
    act(() => {
      useTemplateStore.setState({
        latestSnapshot: makeSnap(0.8, 60),
        snapshotReceivedAt: Date.now(),
      })
      useRuntimeStore.setState({
        latestSnapshot: makeSnap(0.8, 60),
      })
    })

    expect(screen.getByTestId('runtime-field-tank_2.level').textContent).toContain('0.800')
  })

  it('updates stale indicator when stale changes from false to true', () => {
    useTemplateStore.setState({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: makeSnap(0.5, 30),
      snapshotReceivedAt: Date.now(),
      connectionState: 'connected',
      runtimeName: 'second_order_tank',
      cycleTime: 0.5,
      stale: false,
    })
    useRuntimeStore.setState({
      connectionState: 'connected',
      latestSnapshot: makeSnap(0.5, 30),
      cycleTime: 0.5,
      stale: false,
    })

    render(<SecondOrderTankInspector
      selectedObjectId="tank_2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })

    expect(screen.getByTestId('runtime-stale').textContent).toContain('否')

    // stale 从 false → true，必须自动刷新
    act(() => {
      useTemplateStore.setState({ stale: true })
      useRuntimeStore.setState({ stale: true })
    })

    expect(screen.getByTestId('runtime-stale').textContent).toContain('是')
  })

  it('updates connection state in runtime tab on reconnect', () => {
    useTemplateStore.setState({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: makeSnap(0.5, 30),
      snapshotReceivedAt: Date.now(),
      connectionState: 'disconnected',
      runtimeName: 'second_order_tank',
      cycleTime: 0.5,
      stale: true,
    })
    useRuntimeStore.setState({
      connectionState: 'disconnected',
      latestSnapshot: makeSnap(0.5, 30),
      cycleTime: 0.5,
      stale: true,
    })

    render(<SecondOrderTankInspector
      selectedObjectId="tank_2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })

    expect(screen.getByTestId('runtime-connection').textContent).toContain('已断开')

    // 模拟重连成功
    act(() => {
      useTemplateStore.setState({
        connectionState: 'connected',
        stale: false,
        snapshotReceivedAt: Date.now() + 1000,
        latestSnapshot: makeSnap(0.6, 40),
      })
      useRuntimeStore.setState({
        connectionState: 'connected',
        stale: false,
        snapshotReceivedAt: Date.now() + 1000,
        latestSnapshot: makeSnap(0.6, 40),
      })
    })

    expect(screen.getByTestId('runtime-connection').textContent).toContain('已连接')
    expect(screen.getByTestId('runtime-stale').textContent).toContain('否')
  })

  it('shows — for missing snapshot fields (NOT draft fallback)', () => {
    const incompleteSnap: RuntimeSnapshot = {
      // cycleCount / simTime 缺失
      sourceFlow: 0.0012,
      valve: {},
      tank1: {},
      tank2: {},
      pid: { SV: 0.8 },
      _receivedAt: Date.now(),
    }
    useTemplateStore.setState({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: incompleteSnap,
      snapshotReceivedAt: Date.now(),
      connectionState: 'connected',
      runtimeName: 'second_order_tank',
      cycleTime: 0.5,
      stale: false,
    })
    useRuntimeStore.setState({
      connectionState: 'connected',
      latestSnapshot: incompleteSnap,
      cycleTime: 0.5,
    })

    render(<SecondOrderTankInspector
      selectedObjectId="pid2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })

    // pid2.SV 有值
    const svField = screen.getByTestId('runtime-field-pid2.SV')
    expect(svField.textContent).toContain('0.800')

    // pid2.PV 缺失 → — + 缺字段告警
    const pvField = screen.getByTestId('runtime-field-pid2.PV')
    expect(pvField.textContent).toContain('— 缺字段')

    // pid2.MODE 缺失 → — + 缺字段告警
    const modeField = screen.getByTestId('runtime-field-pid2.MODE')
    expect(modeField.textContent).toContain('— 缺字段')
  })

  it('displays runtimeName from status.instance_name, never from draft', () => {
    useTemplateStore.setState({
      runtimeState: 'SIMULATION_RUNNING',
      latestSnapshot: makeSnap(0.5, 30),
      snapshotReceivedAt: Date.now(),
      connectionState: 'connected',
      runtimeName: 'real_runtime_from_status',
      cycleTime: 0.5,
      stale: false,
    })
    useRuntimeStore.setState({
      connectionState: 'connected',
      latestSnapshot: makeSnap(0.5, 30),
      cycleTime: 0.5,
      runtimeName: 'real_runtime_from_status',
    })

    render(<SecondOrderTankInspector
      selectedObjectId="tank_2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })

    expect(screen.getByTestId('runtime-name').textContent).toContain('real_runtime_from_status')
    // 严禁显示 pid2 / tank_2 之类的 Program 实例名
    expect(screen.getByTestId('runtime-name').textContent).not.toContain('pid2')
  })

  it('LT-201 runtime tab displays both ends of its real signal binding', () => {
    useTemplateStore.setState({ runtimeState: 'SIMULATION_RUNNING' })
    useRuntimeStore.setState({
      connectionState: 'connected', stale: false,
      latestSnapshot: makeSnap(0.55, 30), snapshotReceivedAt: Date.now(),
      runtimeName: 'second_order_tank', cycleTime: 0.5,
    })
    render(<SecondOrderTankInspector
      selectedObjectId="lt_201"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })
    expect(screen.getByTestId('runtime-field-tank_2.level').textContent).toContain('0.800')
    expect(screen.getByTestId('runtime-field-pid2.PV').textContent).toContain('0.800')
  })

  it('PID runtime tab includes CSV and SWPN contract tags', () => {
    useTemplateStore.setState({ runtimeState: 'SIMULATION_RUNNING' })
    useRuntimeStore.setState({
      connectionState: 'connected', stale: false,
      latestSnapshot: makeSnap(0.5, 30), snapshotReceivedAt: Date.now(),
      runtimeName: 'second_order_tank', cycleTime: 0.5,
    })
    render(<SecondOrderTankInspector
      selectedObjectId="pid2"
      draft={baseDraft}
      dirtyPaths={new Set()}
      validationErrors={[]}
      validationWarnings={[]}
      onEditField={() => {}}
    />)
    act(() => { screen.getByTestId('tab-runtime').click() })
    expect(screen.getByTestId('runtime-field-pid2.CSV')).toBeTruthy()
    expect(screen.getByTestId('runtime-field-pid2.SWPN')).toBeTruthy()
  })
})
