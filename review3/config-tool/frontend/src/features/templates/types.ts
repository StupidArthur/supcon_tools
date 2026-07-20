import type { config as wailsConfig } from '../../../wailsjs/go/models'

// 模板工作区使用纯接口，避免依赖 Wails 生成类的 convertValues 实例方法。
// 后端 JSON 形状兼容；只需在边界处做一次适配。
//
// 这里直接从 wailsjs/go/models 取类类型，仅用于 import-time 类型推断；
// 实际工作区类型采用独立接口，避免与 Wails 类的 convertValues 方法产生冲突。

export interface ValveConfig {
  fullTravelTime: number
  initialOpening: number
  flowCoefficient: number
  minOpening: number
  maxOpening: number
}

export interface TankConfig {
  height: number
  radius: number
  outletArea: number
  initialLevel: number
}

export interface PIDConfig {
  PB: number
  TI: number
  TD: number
  KD: number
  SV: number
  MV: number
  MODE: number
  SWPN: number
  SVSCL: number
  SVSCH: number
  SVL: number
  SVH: number
  MVSCL: number
  MVSCH: number
  MVL: number
  MVH: number
}

export interface TemplateConfig {
  cycleTime: number
  clockMode: string
  sourceFlow: number
  valve: ValveConfig
  tank1: TankConfig
  tank2: TankConfig
  pid: PIDConfig
}

// FieldPresence 标记白名单字段在磁盘 YAML 中是否真实存在。
// 保存时只有同时位于 modifiedPaths 内的字段才会被写回，避免引入新键。
export interface FieldPresence {
  cycleTime: boolean
  clockMode: boolean
  sourceFlow: boolean
  valve: {
    fullTravelTime: boolean
    initialOpening: boolean
    flowCoefficient: boolean
    minOpening: boolean
    maxOpening: boolean
  }
  tank1: {
    height: boolean
    radius: boolean
    outletArea: boolean
    initialLevel: boolean
  }
  tank2: {
    height: boolean
    radius: boolean
    outletArea: boolean
    initialLevel: boolean
  }
  pid: {
    PB: boolean
    TI: boolean
    TD: boolean
    KD: boolean
    SV: boolean
    MV: boolean
    MODE: boolean
    SWPN: boolean
    SVSCL: boolean
    SVSCH: boolean
    SVL: boolean
    SVH: boolean
    MVSCL: boolean
    MVSCH: boolean
    MVL: boolean
    MVH: boolean
  }
}

export interface TemplateProgramTopology {
  name: string
  type: string
  inputs: Record<string, string>
  executeFirst: boolean
}

export interface TemplateTopology {
  programs: TemplateProgramTopology[]
}

export interface TemplateDocument {
  path: string
  contentHash: string
  config: TemplateConfig
  presence: FieldPresence
  topology: TemplateTopology
  warnings: string[]
}

export interface TemplatePatch {
  path: string
  value: number
}

export interface SaveTemplateRequest {
  sourcePath: string
  targetPath: string
  expectedHash: string
  patches: TemplatePatch[]
  allowOverwrite: boolean
}

export interface SaveTemplateResult {
  newPath: string
  newHash: string
  newDocument: TemplateDocument
}

// ValidationIssue 是单条校验错误或警告；后端 ValidateTemplateConfig 也是同一形状。
export interface ValidationIssue {
  path: string
  level: 'error' | 'warning'
  message: string
}

// TemplateSnapshot 在阶段 4 已经迁移到 features/runtime/types.ts。
// 这里保留一个类型别名指向新位置，避免外部旧 import 报错。
export type { RuntimeSnapshot as TemplateSnapshot } from '../runtime/types'
// 旧版字段引用保留以兼容 0 依赖：仍可访问 TemplateSnapshot 字段。
// 推荐新代码直接 import { RuntimeSnapshot } from '../../runtime/types'。

// 仅用于类型推断：在调用层确认我们使用的字段名与后端 Wails 模型兼容。
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _EnsureCompat = wailsConfig.TemplateConfig

export type TemplateId = 'second_order_tank'

// TemplateDefinition 描述一个固定模板的元数据。
// 阶段 1 只填 second_order_tank；后续阶段会扩展到精馏塔等。
export interface TemplateDefinition {
  id: TemplateId
  displayName: string
  defaultBuiltinPath: string
  // 程序→实例名的只读映射。后续阶段会补 SVG 角色绑定。
  programs: TemplateProgramTopology[]
}

// DraftConfig 是 store 内部维护的可变状态。
// 与 TemplateConfig 的差别：保存时不会自动回写，必须显式经过 Save 流程。
export interface DraftConfig extends TemplateConfig {}

// SavedConfig 是最近一次成功保存并重新读回的快照。
// 注意 latestSnapshot 不得复用此对象。
export interface SavedConfig extends TemplateConfig {
  path: string
  contentHash: string
}

// 模板工作区状态。
// 与 useCanvasStore 独立；保留 useCanvasStore 给通用 DSL 视图。
export interface TemplateWorkspaceState {
  templateId: TemplateId | null
  definition: TemplateDefinition | null

  sourcePath: string | null
  saved: SavedConfig | null
  draft: DraftConfig | null
  savedContentHash: string | null

  // 选中对象 id（用于右侧检查器）。null 表示未选中。
  selectedObjectId: SelectedObjectId | null

  // 脏路径集合（用户编辑但未保存的字段）。
  dirtyPaths: Set<string>

  validationErrors: ValidationIssue[]
  validationWarnings: ValidationIssue[]

  // 当前运行实例采用的配置标识（运行时由后续阶段填写）。
  runningConfigIdentity: RunningConfigIdentity | null

  // 整体状态机（阶段 1 只用 STOPPED_EDITING 与 ERROR）。
  runtimeState: TemplateRuntimeState

  // 最近一次保存的绝对路径与 hash，用于提示用户。
  lastSavedPath: string | null
  lastSavedHash: string | null
}

export type SelectedObjectId =
  | 'source_flow'
  | 'valve_1'
  | 'tank_1'
  | 'tank_2'
  | 'lt_201'
  | 'pid2'

export interface RunningConfigIdentity {
  path: string
  contentHash: string
  startedAt: string
}

export type TemplateRuntimeState =
  | 'STOPPED_EDITING'
  | 'STARTING'
  | 'SIMULATION_RUNNING'
  | 'REALTIME_RUNNING'
  | 'BATCH_RUNNING'
  | 'STOPPING'
  | 'ERROR'

// 默认内置模板路径。运行时由后端校验是否允许覆盖。
export const BUILTIN_TEMPLATE_PATH = 'config/单阀门二阶水箱.yaml'
