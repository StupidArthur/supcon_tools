import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ObjectInspector } from '../ObjectInspector'
import { useTemplateStore } from '../useTemplateStore'
import { SecondOrderTankPage } from './SecondOrderTankPage'
import type { DraftConfig } from '../types'

const config: DraftConfig = {
  cycleTime: 0.5,
  clockMode: 'REALTIME',
  sourceFlow: 0.0012,
  valve: { fullTravelTime: 12, initialOpening: 0, flowCoefficient: 1, minOpening: 0, maxOpening: 100 },
  tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
  tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
  pid: {
    PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
    SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
    MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
  },
}

function seedStore() {
  useTemplateStore.setState({
    templateId: 'second_order_tank',
    definition: {
      id: 'second_order_tank',
      displayName: '单阀门二阶水箱',
      defaultBuiltinPath: 'config/单阀门二阶水箱.yaml',
      programs: [],
    },
    sourcePath: 'G:/repo/config/user-scheme.yaml',
    saved: { ...structuredClone(config), path: 'G:/repo/config/user-scheme.yaml', contentHash: 'saved-hash' },
    draft: structuredClone(config),
    savedContentHash: 'saved-hash',
    selectedObjectId: 'tank_2',
    dirtyPaths: new Set(),
    validationErrors: [],
    validationWarnings: [],
    latestSnapshot: null,
    snapshotReceivedAt: null,
    runningConfigIdentity: null,
    runtimeState: 'STOPPED_EDITING',
  })
}

describe('SecondOrderTankPage integration', () => {
  beforeEach(seedStore)
  afterEach(() => useTemplateStore.getState().reset())

  it('inspector edit updates draft and dirty without changing saved', () => {
    render(<ObjectInspector />)
    const input = screen.getByTestId('input-tank2.height')
    fireEvent.change(input, { target: { value: '1.5' } })
    fireEvent.blur(input)

    const state = useTemplateStore.getState()
    expect(state.draft?.tank2.height).toBe(1.5)
    expect(state.saved?.tank2.height).toBe(1.2)
    expect(state.dirtyPaths.has('tank2.height')).toBe(true)
    expect(state.validationErrors).toEqual([])
  })

  it('keeps the diagram, inspector, and key controls present at 1024x700', () => {
    render(
      <div style={{ width: 1024, height: 700 }}>
        <SecondOrderTankPage />
      </div>
    )

    expect(screen.getByTestId('second-order-tank-page')).toBeTruthy()
    expect(screen.getByTestId('diagram-area').className).toContain('min-w-0')
    expect(screen.getByTestId('inspector-panel').className).toContain('w-80')
    expect(screen.getByTestId('save-button')).toBeTruthy()
    expect(screen.getByTestId('save-as-button')).toBeTruthy()
    expect(screen.getByTestId('advanced-view-button')).toBeTruthy()
  })
})
