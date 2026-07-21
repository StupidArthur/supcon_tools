import { create } from 'zustand'
import type {
  DraftConfig,
  RunningConfigIdentity,
  SavedConfig,
  SelectedObjectId,
  TemplateDefinition,
  TemplateId,
  TemplatePatch,
  TemplateRuntimeState,
  TemplateDocument,
  ValidationIssue,
} from './types'
import { BUILTIN_TEMPLATE_PATH } from './types'
import {
  configsEqual,
  diffPaths,
  validateConfig,
  warningsForConfig,
} from './secondOrderTank/validationRules'
import { bindValidateConfig } from './secondOrderTank/validation'
import { templateApi } from '../../lib/api'
import type { SaveTemplateResult } from './types'

// 阶段 4 把 latestSnapshot 类型迁移到 runtime 领域；这里只保留模板侧的引用。
import type { ConnectionState, RuntimeSnapshot } from '../runtime/types'

// useTemplateStore 是阶段 1 模板工作区的状态管理器。
//
// 关键不变量：
//   - draft 修改不直接影响 saved；保存时由用户显式触发 Save。
//   - latestSnapshot 与 snapshotReceivedAt 是独立的运行时只读字段，绝不复用 draft。
//     阶段 1 全部为 null；阶段 4 接入 WebSocket 后由 ws.subscribe() 写入。
//   - loadFromPath 失败时进入 ERROR 状态，并把 loadError 字段写入。
//   - 校验采用后端 ValidateTemplateConfig 同一份逻辑（frontend validation.ts 镜像）；
//     不可达目标流量与 Tank 1 预计溢流是 BLOCKING 错误。

const SECOND_ORDER_TANK_TOPOLOGY: TemplateDefinition['programs'] = [
  {
    name: 'source_flow',
    type: 'Variable',
    inputs: {},
    executeFirst: false,
  },
  {
    name: 'valve_1',
    type: 'VALVE',
    inputs: {
      target_opening: 'pid2.MV',
      inlet_flow: 'source_flow',
    },
    executeFirst: false,
  },
  {
    name: 'tank_1',
    type: 'CYLINDRICAL_TANK',
    inputs: {
      inlet_flow: 'valve_1.outlet_flow',
    },
    executeFirst: false,
  },
  {
    name: 'tank_2',
    type: 'CYLINDRICAL_TANK',
    inputs: {
      inlet_flow: 'tank_1.outlet_flow',
    },
    executeFirst: false,
  },
  {
    name: 'pid2',
    type: 'PID',
    inputs: {
      PV: 'tank_2.level',
    },
    executeFirst: true,
  },
]

const SECOND_ORDER_TANK_DEFINITION: TemplateDefinition = {
  id: 'second_order_tank',
  displayName: '单阀门二阶水箱',
  defaultBuiltinPath: BUILTIN_TEMPLATE_PATH,
  programs: SECOND_ORDER_TANK_TOPOLOGY,
}

function loadedDocumentState(doc: TemplateDocument) {
  const draft = cloneConfig(doc.config)
  const saved: SavedConfig = {
    ...draft,
    path: doc.path,
    contentHash: doc.contentHash,
  }
  const issues = validateConfig(draft)
  const splitted = splitIssues(issues)
  return {
    templateId: 'second_order_tank' as const,
    definition: SECOND_ORDER_TANK_DEFINITION,
    sourcePath: doc.path,
    saved,
    draft,
    savedContentHash: doc.contentHash,
    selectedObjectId: null,
    dirtyPaths: new Set<string>(),
    validationErrors: splitted.errors,
    validationWarnings: [...splitted.warnings, ...warningsForConfig(draft)],
    latestSnapshot: null,
    snapshotReceivedAt: null,
    loadError: null,
    saveError: null,
    runtimeState: 'STOPPED_EDITING' as const,
    runningConfigIdentity: null,
    runningConfig: null,
    lastSavedPath: doc.path,
    lastSavedHash: doc.contentHash,
  }
}

function loadFailureState(err: unknown) {
  return {
    runtimeState: 'ERROR' as const,
    loadError: err instanceof Error ? err.message : String(err),
    draft: null,
    saved: null,
    savedContentHash: null,
    validationErrors: [] as ValidationIssue[],
    validationWarnings: [] as ValidationIssue[],
  }
}

interface TemplateStoreState {
  templateId: TemplateId | null
  definition: TemplateDefinition | null

  sourcePath: string | null
  saved: SavedConfig | null
  draft: DraftConfig | null
  savedContentHash: string | null

  selectedObjectId: SelectedObjectId | null

  dirtyPaths: Set<string>
  validationErrors: ValidationIssue[]
  validationWarnings: ValidationIssue[]

  // 运行时只读 snapshot：阶段 1 全部为 null；阶段 4 由 ws.subscribe 写入。
  // 这里只放透传引用，真正的状态在 runtime store。
  latestSnapshot: RuntimeSnapshot | null
  snapshotReceivedAt: number | null
  connectionState: ConnectionState
  stale: boolean
  cycleTime: number
  runtimeName: string | null

  // 加载/保存错误状态。
  loadError: string | null
  saveError: string | null

  runningConfigIdentity: RunningConfigIdentity | null
  // 进程启动时采用的配置快照。运行态几何显示只能读取该冻结值，不能读取正在编辑的 draft。
  runningConfig: DraftConfig | null
  runtimeState: TemplateRuntimeState

  lastSavedPath: string | null
  lastSavedHash: string | null

  // 操作
  loadBuiltin: () => Promise<void>
  loadFromPath: (path: string) => Promise<void>
  selectObject: (id: SelectedObjectId | null) => void
  editField: (fieldPath: string, value: number | string) => void
  save: (opts?: { targetPath?: string; allowOverwrite?: boolean }) => Promise<SaveTemplateResult>
  setRuntimeState: (s: TemplateRuntimeState) => void
  setRunningIdentity: (id: RunningConfigIdentity | null) => void
  // 阶段 4 runtime 同步接口：模板 store 只读透传
  setRuntimeSnapshot: (snap: RuntimeSnapshot | null, receivedAt: number | null) => void
  setRuntimeConnection: (state: ConnectionState, runtimeName: string | null, cycleTime: number) => void
  setRuntimeStale: (stale: boolean) => void
  reset: () => void
}

// 把后端返回的 TemplateConfig 深拷贝成可变 DraftConfig。
function cloneConfig(cfg: TemplateDocumentConfig): DraftConfig {
  return {
    cycleTime: cfg.cycleTime,
    clockMode: cfg.clockMode,
    sourceFlow: cfg.sourceFlow,
    valve: { ...cfg.valve },
    tank1: { ...cfg.tank1 },
    tank2: { ...cfg.tank2 },
    pid: { ...cfg.pid },
  }
}

function patchValueForPath(draft: DraftConfig, fieldPath: string, value: number | string): DraftConfig {
  const next = cloneConfig(draft)
  const segs = fieldPath.split('.')
  if (segs.length === 1) {
    if (fieldPath === 'cycleTime' && typeof value === 'number') next.cycleTime = value
    else if (fieldPath === 'clockMode' && typeof value === 'string') next.clockMode = value
    else if (fieldPath === 'sourceFlow' && typeof value === 'number') next.sourceFlow = value
    return next
  }
  const [group, key] = segs
  if (group === 'valve' && typeof value === 'number') {
    ;(next.valve as unknown as Record<string, number>)[key] = value
  } else if (group === 'tank1' && typeof value === 'number') {
    ;(next.tank1 as unknown as Record<string, number>)[key] = value
  } else if (group === 'tank2' && typeof value === 'number') {
    ;(next.tank2 as unknown as Record<string, number>)[key] = value
  } else if (group === 'pid' && typeof value === 'number') {
    ;(next.pid as unknown as Record<string, number>)[key] = value
  }
  // tank2.height 同步 PID SVSCH/SVH
  if (group === 'tank2' && key === 'height' && typeof value === 'number') {
    next.pid.SVSCH = value
    next.pid.SVH = value
  }
  return next
}

// 把 draft 的差异转成白名单 patches。
// 阶段 1 只覆盖 number 字段；clockMode 暂不支持持久化（默认 REALTIME 即可）。
function buildPatches(saved: DraftConfig, draft: DraftConfig): TemplatePatch[] {
  const patches: TemplatePatch[] = []
  if (saved.cycleTime !== draft.cycleTime) patches.push({ path: 'cycleTime', value: draft.cycleTime })
  if (saved.sourceFlow !== draft.sourceFlow) patches.push({ path: 'sourceFlow', value: draft.sourceFlow })
  for (const k of ['fullTravelTime', 'initialOpening', 'flowCoefficient', 'minOpening', 'maxOpening'] as const) {
    if (saved.valve[k] !== draft.valve[k]) patches.push({ path: `valve.${k}`, value: draft.valve[k] })
  }
  for (const k of ['height', 'radius', 'outletArea', 'initialLevel'] as const) {
    if (saved.tank1[k] !== draft.tank1[k]) patches.push({ path: `tank1.${k}`, value: draft.tank1[k] })
    if (saved.tank2[k] !== draft.tank2[k]) patches.push({ path: `tank2.${k}`, value: draft.tank2[k] })
  }
  for (const k of [
    'PB', 'TI', 'TD', 'KD', 'SV', 'MV',
    'MODE', 'SWPN',
    'SVSCL', 'SVSCH', 'SVL', 'SVH',
    'MVSCL', 'MVSCH', 'MVL', 'MVH',
  ] as const) {
    if (saved.pid[k] !== draft.pid[k]) patches.push({ path: `pid.${k}`, value: draft.pid[k] })
  }
  return patches
}

// 与 Wails models.TemplateDocument.Config 形状对齐的别名（避免依赖完整 model 类型）。
type TemplateDocumentConfig = {
  cycleTime: number
  clockMode: string
  sourceFlow: number
  valve: { fullTravelTime: number; initialOpening: number; flowCoefficient: number; minOpening: number; maxOpening: number }
  tank1: { height: number; radius: number; outletArea: number; initialLevel: number }
  tank2: { height: number; radius: number; outletArea: number; initialLevel: number }
  pid: { PB: number; TI: number; TD: number; KD: number; SV: number; MV: number; MODE: number; SWPN: number; SVSCL: number; SVSCH: number; SVL: number; SVH: number; MVSCL: number; MVSCH: number; MVL: number; MVH: number }
}

function splitIssues(all: ValidationIssue[]): { errors: ValidationIssue[]; warnings: ValidationIssue[] } {
  const errs: ValidationIssue[] = []
  const warns: ValidationIssue[] = []
  for (const it of all) {
    if (it.level === 'error') errs.push(it)
    else warns.push(it)
  }
  return { errors: errs, warnings: warns }
}

export const useTemplateStore = create<TemplateStoreState>((set, get) => ({
  templateId: null,
  definition: null,
  sourcePath: null,
  saved: null,
  draft: null,
  savedContentHash: null,
  selectedObjectId: null,
  dirtyPaths: new Set(),
  validationErrors: [],
  validationWarnings: [],
latestSnapshot: null,
    snapshotReceivedAt: null,
    connectionState: 'idle',
    stale: false,
    cycleTime: 0.5,
    runtimeName: null,
    loadError: null,
    saveError: null,
    runningConfigIdentity: null,
    runningConfig: null,
    runtimeState: 'STOPPED_EDITING',
    lastSavedPath: null,
    lastSavedHash: null,

    loadBuiltin: async () => {
    try {
      const doc = await templateApi.loadBuiltin()
      set(loadedDocumentState(doc))
    } catch (err) {
      set(loadFailureState(err))
    }
  },

  loadFromPath: async (path: string) => {
    let doc: Awaited<ReturnType<typeof templateApi.load>>
    const prev = get()
    const keepRuntime =
      prev.runtimeState === 'SIMULATION_RUNNING' ||
      prev.runtimeState === 'REALTIME_RUNNING' ||
      prev.runtimeState === 'BATCH_RUNNING'
    try {
      doc = await templateApi.load(path)
    } catch (err) {
      set(loadFailureState(err))
      if (keepRuntime) {
        set({
          runtimeState: prev.runtimeState,
          runningConfigIdentity: prev.runningConfigIdentity,
          runningConfig: prev.runningConfig,
        })
      }
      return
    }
    const base = loadedDocumentState(doc)
    if (keepRuntime) {
      set({
        ...base,
        runtimeState: prev.runtimeState,
        runningConfigIdentity: prev.runningConfigIdentity,
        runningConfig: prev.runningConfig,
      })
    } else {
      set(base)
    }
  },

  selectObject: (id) => set({ selectedObjectId: id }),

  editField: (fieldPath, value) => {
    const state = get()
    if (!state.draft || !state.saved) return
    const nextDraft = patchValueForPath(state.draft, fieldPath, value)
    const dirtySet = new Set(diffPaths(nextDraft, state.saved))
    const issues = validateConfig(nextDraft)
    const splitted = splitIssues(issues)
    const keepRuntimeState =
      state.runtimeState === 'SIMULATION_RUNNING' ||
      state.runtimeState === 'REALTIME_RUNNING' ||
      state.runtimeState === 'BATCH_RUNNING'
    set({
      draft: nextDraft,
      dirtyPaths: dirtySet,
      validationErrors: splitted.errors,
      validationWarnings: [...splitted.warnings, ...warningsForConfig(nextDraft)],
      runtimeState: keepRuntimeState ? state.runtimeState : 'STOPPED_EDITING',
    })
  },

  save: async (opts) => {
    const state = get()
    const keepRuntimeState =
      state.runtimeState === 'SIMULATION_RUNNING' ||
      state.runtimeState === 'REALTIME_RUNNING' ||
      state.runtimeState === 'BATCH_RUNNING'
    if (!state.draft || !state.saved || !state.savedContentHash) {
      const err = new Error('无可保存的草稿')
      set({
        saveError: err.message,
        runtimeState: keepRuntimeState ? state.runtimeState : 'ERROR',
      })
      throw err
    }
    if (state.validationErrors.length > 0) {
      const err = new Error('存在校验错误，无法保存')
      set({
        saveError: err.message,
        runtimeState: keepRuntimeState ? state.runtimeState : 'ERROR',
      })
      throw err
    }
    const patches = buildPatches(state.saved, state.draft)
    if (patches.length === 0) {
      const emptyResult: SaveTemplateResult = {
        newPath: state.sourcePath ?? '',
        newHash: state.savedContentHash,
        newDocument: {
          path: state.sourcePath ?? '',
          contentHash: state.savedContentHash,
          config: cloneConfig(state.draft),
          presence: state.draft ? emptyPresence() : emptyPresence(),
          topology: { programs: state.definition?.programs ?? [] },
          warnings: [],
        },
      }
      return emptyResult
    }
    const target = opts?.targetPath ?? state.sourcePath ?? ''
    let result: SaveTemplateResult
    try {
      result = await templateApi.save({
        sourcePath: state.sourcePath ?? '',
        targetPath: target,
        expectedHash: state.savedContentHash,
        patches,
        allowOverwrite: opts?.allowOverwrite ?? false,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      set({
        saveError: msg,
        runtimeState: keepRuntimeState ? state.runtimeState : 'ERROR',
      })
      throw err
    }
    const saved: SavedConfig = {
      ...cloneConfig(result.newDocument.config),
      path: result.newPath,
      contentHash: result.newHash,
    }
    const issues = validateConfig(saved)
    const splitted = splitIssues(issues)
    set({
      sourcePath: result.newPath,
      saved,
      savedContentHash: result.newHash,
      draft: cloneConfig(result.newDocument.config),
      dirtyPaths: new Set(),
      validationErrors: splitted.errors,
      validationWarnings: [...splitted.warnings, ...warningsForConfig(saved)],
      saveError: null,
      runtimeState: keepRuntimeState
        ? state.runtimeState
        : splitted.errors.length > 0 ? 'ERROR' : 'STOPPED_EDITING',
      lastSavedPath: result.newPath,
      lastSavedHash: result.newHash,
    })
    return result
  },

  setRuntimeState: (s) => set({ runtimeState: s }),
  setRunningIdentity: (id) => set((state) => ({
    runningConfigIdentity: id,
    runningConfig: id && state.saved ? cloneConfig(state.saved) : null,
  })),

  setRuntimeSnapshot: (snap, receivedAt) =>
    set({ latestSnapshot: snap, snapshotReceivedAt: receivedAt }),
  setRuntimeConnection: (state, runtimeName, cycleTime) =>
    set({ connectionState: state, runtimeName, cycleTime }),
  setRuntimeStale: (stale) => set({ stale }),

  reset: () => set({
    templateId: null,
    definition: null,
    sourcePath: null,
    saved: null,
    draft: null,
    savedContentHash: null,
    selectedObjectId: null,
    dirtyPaths: new Set(),
    validationErrors: [],
    validationWarnings: [],
    latestSnapshot: null,
    snapshotReceivedAt: null,
    connectionState: 'idle',
    stale: false,
    cycleTime: 0.5,
    runtimeName: null,
    loadError: null,
    saveError: null,
    runningConfigIdentity: null,
    runningConfig: null,
    runtimeState: 'STOPPED_EDITING',
    lastSavedPath: null,
    lastSavedHash: null,
  }),
}))

// 当本地短路返回 SaveTemplateResult 时，presence 没有真实值。
// 空实现避免 runtime 错误；后续阶段保存路径不会触发此分支。
function emptyPresence(): any {
  return {
    cycleTime: false,
    clockMode: false,
    sourceFlow: false,
    valve: { fullTravelTime: false, initialOpening: false, flowCoefficient: false, minOpening: false, maxOpening: false },
    tank1: { height: false, radius: false, outletArea: false, initialLevel: false },
    tank2: { height: false, radius: false, outletArea: false, initialLevel: false },
    pid: { PB: false, TI: false, TD: false, KD: false, SV: false, MV: false, MODE: false, SWPN: false, SVSCL: false, SVSCH: false, SVL: false, SVH: false, MVSCL: false, MVSCH: false, MVL: false, MVH: false },
  }
}

// 便利 selector：判断两态是否一致。
export function selectIsDraftClean(state: TemplateStoreState): boolean {
  return state.dirtyPaths.size === 0
}

export function selectIsSavedEqualsRunning(state: TemplateStoreState): boolean {
  const running = state.runningConfigIdentity
  if (!running) return false
  return running.contentHash === state.savedContentHash
}

export function selectConfigsEqual(a: DraftConfig | null, b: DraftConfig | null): boolean {
  return configsEqual(a, b)
}

// Wire formal validateBeforeSave adapter to the same validateConfig rules.
bindValidateConfig((doc) => validateConfig(doc as DraftConfig))
