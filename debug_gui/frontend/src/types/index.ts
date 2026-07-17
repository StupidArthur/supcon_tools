/** 运行模式 */
export type RunMode = 'batch' | 'realtime'

/** 引擎状态 */
export interface EngineStatus {
  running: boolean
  pid: number
  configPath: string
  mode: string
  port: number
}

/** YAML 配置（从 Go 侧解析） */
export interface YAMLConfig {
  clock: {
    mode: string
    cycleTime: number
  }
  program: ProgramItem[]
}

/** YAML 中的单个 program 项 */
export interface ProgramItem {
  name: string
  type: string
  expression: string
  initArgs: Record<string, any>
  displayArgs: string[]
}

/** 批量仿真结果 */
export interface BatchResult {
  columns: string[]
  rows: Record<string, any>[]
}

/** 日志条目 */
export interface LogEntry {
  ts: number
  source: string
  text: string
}
