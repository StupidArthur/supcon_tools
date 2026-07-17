// Wails JS bindings 类型声明

export namespace bindings {
  export interface StartParams {
    workDir: string
    pythonPath: string
    configPath: string
    mode: string
    cycleTime: number
    port: number
  }

  export interface BatchParams {
    workDir: string
    pythonPath: string
    configPath: string
    cycles: number
    cycleTime: number
  }

  export interface EngineStatus {
    running: boolean
    pid: number
    configPath: string
    mode: string
    port: number
  }

  export interface BatchResult {
    columns: string[]
    rows: Record<string, any>[]
  }

  export interface ClockSection {
    mode: string
    cycleTime: number
  }

  export interface ProgramSection {
    name: string
    type: string
    expression: string
    initArgs: Record<string, any>
    displayArgs: string[]
  }

  export interface YAMLConfig {
    clock: ClockSection
    program: ProgramSection[]
  }
}

export declare function BrowseDir(title: string): Promise<string>
export declare function BrowseExe(): Promise<string>
export declare function BrowseYAML(): Promise<string>
export declare function SaveCSVFile(): Promise<string>
export declare function ListConfigs(workDir: string): Promise<string[]>
export declare function ParseYAMLConfig(yamlPath: string): Promise<bindings.YAMLConfig>
export declare function StartEngine(params: bindings.StartParams): Promise<bindings.EngineStatus>
export declare function StartBatch(params: bindings.BatchParams): Promise<string>
export declare function ReadBatchResult(csvPath: string): Promise<bindings.BatchResult>
export declare function ExportBatch(params: bindings.BatchParams, exportPath: string): Promise<void>
export declare function StopEngine(): Promise<void>
export declare function GetStatus(): Promise<bindings.EngineStatus>
export declare function CleanupTempFile(path: string): Promise<void>
