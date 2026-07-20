import { beforeEach, describe, expect, it, vi } from 'vitest'
import { templateApi } from '../../lib/api'
import type { TemplateDocument } from './types'
import { useTemplateStore } from './useTemplateStore'

const document: TemplateDocument = {
  path: 'G:/repo/config/单阀门二阶水箱.yaml',
  contentHash: 'hash-1',
  config: {
    cycleTime: 0.5,
    clockMode: 'REALTIME',
    sourceFlow: 0.0012,
    valve: { fullTravelTime: 10, initialOpening: 0, flowCoefficient: 1, minOpening: 0, maxOpening: 100 },
    tank1: { height: 1.2, radius: 0.15, outletArea: 0.00025, initialLevel: 0.15 },
    tank2: { height: 1.2, radius: 0.15, outletArea: 0.0002, initialLevel: 0.1 },
    pid: {
      PB: 30, TI: 90, TD: 20, KD: 10, SV: 0.8, MV: 0, MODE: 5, SWPN: 1,
      SVSCL: 0, SVSCH: 1.2, SVL: 0, SVH: 1.2,
      MVSCL: 0, MVSCH: 100, MVL: 0, MVH: 100,
    },
  },
  presence: {
    cycleTime: true, clockMode: true, sourceFlow: true,
    valve: { fullTravelTime: true, initialOpening: true, flowCoefficient: false, minOpening: false, maxOpening: false },
    tank1: { height: true, radius: true, outletArea: true, initialLevel: true },
    tank2: { height: true, radius: true, outletArea: true, initialLevel: true },
    pid: {
      PB: true, TI: true, TD: true, KD: true, SV: true, MV: true, MODE: true, SWPN: true,
      SVSCL: true, SVSCH: true, SVL: true, SVH: true,
      MVSCL: true, MVSCH: true, MVL: true, MVH: true,
    },
  },
  topology: { programs: [] },
  warnings: [],
}

describe('useTemplateStore', () => {
  beforeEach(() => {
    useTemplateStore.getState().reset()
    vi.restoreAllMocks()
  })

  it('loads the builtin through the backend resolver', async () => {
    const loadBuiltin = vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    const loadByPath = vi.spyOn(templateApi, 'load')

    await useTemplateStore.getState().loadBuiltin()

    expect(loadBuiltin).toHaveBeenCalledOnce()
    expect(loadByPath).not.toHaveBeenCalled()
    expect(useTemplateStore.getState().sourcePath).toBe(document.path)
  })

  it('tracks dirty paths while keeping invalid editing in STOPPED_EDITING', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()

    useTemplateStore.getState().editField('tank2.radius', -1)
    expect(useTemplateStore.getState().dirtyPaths.has('tank2.radius')).toBe(true)
    expect(useTemplateStore.getState().validationErrors.length).toBeGreaterThan(0)
    expect(useTemplateStore.getState().runtimeState).toBe('STOPPED_EDITING')

    useTemplateStore.getState().editField('tank2.radius', document.config.tank2.radius)
    expect(useTemplateStore.getState().dirtyPaths.size).toBe(0)
  })

  it('does not mix draft edits with saved, running identity, or snapshots', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().setRunningIdentity({ path: document.path, contentHash: 'running-hash', startedAt: '2026-07-19T00:00:00Z' })

    useTemplateStore.getState().editField('tank2.radius', 0.18)
    const state = useTemplateStore.getState()
    expect(state.draft?.tank2.radius).toBe(0.18)
    expect(state.saved?.tank2.radius).toBe(0.15)
    expect(state.runningConfigIdentity?.contentHash).toBe('running-hash')
    expect(state.latestSnapshot).toBeNull()
    expect(state.snapshotReceivedAt).toBeNull()
  })

  it('running edit changes only draft and keeps runtime state, identity, and frozen config', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    const identity = { path: document.path, contentHash: 'running-hash', startedAt: '2026-07-19T00:00:00Z' }
    useTemplateStore.getState().setRunningIdentity(identity)
    useTemplateStore.getState().setRuntimeState('SIMULATION_RUNNING')

    useTemplateStore.getState().editField('tank2.height', 2.4)
    const state = useTemplateStore.getState()
    expect(state.runtimeState).toBe('SIMULATION_RUNNING')
    expect(state.draft?.tank2.height).toBe(2.4)
    expect(state.runningConfig?.tank2.height).toBe(1.2)
    expect(state.runningConfigIdentity).toEqual(identity)
  })

  it('saving draft during a run keeps running identity and frozen configuration', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    const identity = { path: document.path, contentHash: 'running-hash', startedAt: '2026-07-19T00:00:00Z' }
    useTemplateStore.getState().setRunningIdentity(identity)
    useTemplateStore.getState().setRuntimeState('SIMULATION_RUNNING')
    useTemplateStore.getState().editField('sourceFlow', 0.0013)
    const newDocument = structuredClone(document)
    newDocument.contentHash = 'saved-hash-2'
    newDocument.config.sourceFlow = 0.0013
    vi.spyOn(templateApi, 'save').mockResolvedValue({
      newPath: document.path,
      newHash: 'saved-hash-2',
      newDocument,
    })

    await useTemplateStore.getState().save()
    const state = useTemplateStore.getState()
    expect(state.runtimeState).toBe('SIMULATION_RUNNING')
    expect(state.runningConfigIdentity).toEqual(identity)
    expect(state.runningConfig?.sourceFlow).toBe(0.0012)
    expect(state.saved?.sourceFlow).toBe(0.0013)
  })

  it('stage 4: setRuntimeSnapshot writes latestSnapshot without mutating draft or saved', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    const initialDraftRadius = useTemplateStore.getState().draft!.tank2.radius
    const initialSavedRadius = useTemplateStore.getState().saved!.tank2.radius
    const snap = {
      cycleCount: 5,
      simTime: 2.5,
      sourceFlow: 0.0012,
      valve: { targetOpening: 80, currentOpening: 65, inletFlow: 0.001, outletFlow: 0.0005 },
      tank1: { level: 0.4, inletFlow: 0.0005, outletFlow: 0.0003 },
      tank2: { level: 0.6, inletFlow: 0.0003, outletFlow: 0.0002 },
      pid: { PV: 0.6, SV: 0.8, CSV: 0, MV: 65, PB: 30, TI: 90, TD: 20, KD: 10, MODE: 5, SWPN: 1 },
      _receivedAt: 1000,
    }
    useTemplateStore.getState().setRuntimeSnapshot(snap, 1000)
    const state = useTemplateStore.getState()
    expect(state.latestSnapshot).toBe(snap)
    expect(state.snapshotReceivedAt).toBe(1000)
    // draft 与 saved 完全不变
    expect(state.draft!.tank2.radius).toBe(initialDraftRadius)
    expect(state.saved!.tank2.radius).toBe(initialSavedRadius)
  })

  it('stage 4: setRuntimeConnection updates connection/runtimename/cycleTime', () => {
    useTemplateStore.getState().setRuntimeConnection('connected', 'second_order_tank', 0.5)
    const state = useTemplateStore.getState()
    expect(state.connectionState).toBe('connected')
    expect(state.runtimeName).toBe('second_order_tank')
    expect(state.cycleTime).toBe(0.5)
  })

  it('stage 4: setRuntimeStale updates stale flag independently', () => {
    useTemplateStore.getState().setRuntimeStale(true)
    expect(useTemplateStore.getState().stale).toBe(true)
    useTemplateStore.getState().setRuntimeStale(false)
    expect(useTemplateStore.getState().stale).toBe(false)
  })

  it('stage 4: reset clears runtime fields', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().setRuntimeConnection('connected', 'second_order_tank', 0.5)
    useTemplateStore.getState().setRuntimeStale(true)
    useTemplateStore.getState().reset()
    const state = useTemplateStore.getState()
    expect(state.connectionState).toBe('idle')
    expect(state.runtimeName).toBeNull()
    expect(state.cycleTime).toBe(0.5)
    expect(state.stale).toBe(false)
    expect(state.latestSnapshot).toBeNull()
  })
})
