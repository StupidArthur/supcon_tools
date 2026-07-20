/**
 * Stage 1 reviewer acceptance: saved / draft / running identity separation.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { templateApi } from '../../src/lib/api'
import type { TemplateDocument } from '../../src/features/templates/types'
import { useTemplateStore } from '../../src/features/templates/useTemplateStore'

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

describe('stage 1 template store acceptance', () => {
  beforeEach(() => {
    useTemplateStore.getState().reset()
    vi.restoreAllMocks()
  })

  it('keeps saved and draft equal after load but as independent object identities', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    const state = useTemplateStore.getState()
    expect(state.saved?.tank2.radius).toBe(state.draft?.tank2.radius)
    expect(state.saved).not.toBe(state.draft)
  })

  it('edits only mutate draft and dirtyPaths; reverting clears dirty', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().editField('tank2.radius', 0.18)
    expect(useTemplateStore.getState().draft?.tank2.radius).toBe(0.18)
    expect(useTemplateStore.getState().saved?.tank2.radius).toBe(0.15)
    expect(useTemplateStore.getState().dirtyPaths.has('tank2.radius')).toBe(true)
    useTemplateStore.getState().editField('tank2.radius', 0.15)
    expect(useTemplateStore.getState().dirtyPaths.has('tank2.radius')).toBe(false)
  })

  it('running identity is not affected by draft edits', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().setRunningIdentity({
      path: document.path,
      contentHash: 'running-hash',
      startedAt: '2026-07-19T00:00:00Z',
    })
    useTemplateStore.getState().editField('tank2.radius', 0.2)
    expect(useTemplateStore.getState().runningConfigIdentity?.contentHash).toBe('running-hash')
    expect(useTemplateStore.getState().latestSnapshot).toBeNull()
  })

  it('save failure does not update saved; success syncs and clears dirty', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().editField('tank2.radius', 0.18)
    vi.spyOn(templateApi, 'save').mockRejectedValueOnce(new Error('disk full'))
    await expect(
      useTemplateStore.getState().save({ targetPath: 'G:/tmp/out.yaml', allowOverwrite: true }),
    ).rejects.toThrow()
    expect(useTemplateStore.getState().saved?.tank2.radius).toBe(0.15)
    expect(useTemplateStore.getState().dirtyPaths.has('tank2.radius')).toBe(true)

    const newDocument = structuredClone(document)
    newDocument.path = 'G:/tmp/out.yaml'
    newDocument.contentHash = 'hash-2'
    newDocument.config.tank2.radius = 0.18
    vi.spyOn(templateApi, 'save').mockResolvedValueOnce({
      newPath: 'G:/tmp/out.yaml',
      newHash: 'hash-2',
      newDocument,
    })
    await useTemplateStore.getState().save({ targetPath: 'G:/tmp/out.yaml', allowOverwrite: true })
    expect(useTemplateStore.getState().saved?.tank2.radius).toBe(0.18)
    expect(useTemplateStore.getState().draft?.tank2.radius).toBe(0.18)
    expect(useTemplateStore.getState().dirtyPaths.size).toBe(0)
  })

  it('reset clears template state', async () => {
    vi.spyOn(templateApi, 'loadBuiltin').mockResolvedValue(document)
    await useTemplateStore.getState().loadBuiltin()
    useTemplateStore.getState().reset()
    const state = useTemplateStore.getState()
    expect(state.saved).toBeNull()
    expect(state.draft).toBeNull()
    expect(state.sourcePath).toBeNull()
  })
})
