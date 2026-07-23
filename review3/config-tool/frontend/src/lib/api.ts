// Thin wrapper around the Wails-generated bindings.
//
// 阶段 0 范围：只做一层 re-export，不在 wrapper 中维护业务状态。
// 所有领域逻辑（保存策略、模板校验、运行快照缓存等）由调用方或后续阶段的 store 处理。

import * as ComponentBinding from '../../wailsjs/go/bindings/ComponentBinding'
import * as ConfigBinding from '../../wailsjs/go/bindings/ConfigBinding'
import * as SystemBinding from '../../wailsjs/go/bindings/SystemBinding'
import * as TemplateConfigBinding from '../../wailsjs/go/bindings/TemplateConfigBinding'
import * as RealtimeProjectBinding from '../../wailsjs/go/bindings/RealtimeProjectBinding'
import * as RealtimeRuntimeBinding from '../../wailsjs/go/bindings/RealtimeRuntimeBinding'
import type { ExportFormat } from './exportTypes'

// 模板领域类型集中在 features/templates/types.ts，这里只暴露运行时 API。
// 注意：本文件不再 re-export 领域类型，避免形成 types.ts <-> api.ts 循环依赖。
// 调用方按需 import 'features/templates/types'。

export const componentApi = {
  list: () => ComponentBinding.List(),
}

export const configApi = {
  importYAML: (path: string) => ConfigBinding.ImportYAML(path),
  exportYAML: (canvas: any, path: string) => ConfigBinding.ExportYAML(canvas, path),
  validate: (canvas: any) => ConfigBinding.Validate(canvas),
  loadCanvas: (path: string) => ConfigBinding.LoadCanvas(path),
  saveCanvas: (canvas: any, path: string) => ConfigBinding.SaveCanvas(canvas, path),
}

export const templateApi = {
  loadBuiltin: () =>
    TemplateConfigBinding.LoadBuiltinTemplate() as unknown as Promise<import('../features/templates/types').TemplateDocument>,
  load: (path: string) =>
    TemplateConfigBinding.LoadTemplate(path) as unknown as Promise<import('../features/templates/types').TemplateDocument>,
  save: (req: import('../features/templates/types').SaveTemplateRequest) =>
    TemplateConfigBinding.SaveTemplate(req as any) as unknown as Promise<import('../features/templates/types').SaveTemplateResult>,
  validate: (cfg: import('../features/templates/types').TemplateConfig) =>
    TemplateConfigBinding.ValidateTemplateConfig(cfg as any) as unknown as Promise<import('../features/templates/types').ValidationIssue[]>,
  isBuiltin: (path: string) => TemplateConfigBinding.IsBuiltinTemplate(path),
  applyRuntimeOverrides: (req: {
    targetPath: string
    expectedHash: string
    overrides: Record<string, number>
    includeMV: boolean
  }) => TemplateConfigBinding.ApplyRuntimeOverrides(req),
}

export const systemApi = {
  getDataFactoryPath: () => SystemBinding.GetDataFactoryPath(),
  browseExe: () => SystemBinding.BrowseExe(),
  listConfigs: () => SystemBinding.ListConfigs(),
  start: (params: any) => SystemBinding.Start(params as any),
  stop: () => SystemBinding.Stop(),
  status: () => SystemBinding.Status() as any,
  openYAMLFile: () => SystemBinding.OpenYAMLFile(),
  saveYAMLFile: () => SystemBinding.SaveYAMLFile(),
  runBatch: (configPath: string, cycles: number) =>
    SystemBinding.RunBatch(configPath, cycles),
  exportBatch: (configPath: string, cycles: number, exportPath: string) =>
    SystemBinding.ExportBatch(configPath, cycles, exportPath),
  exportBatchFormatted: (
    configPath: string,
    cycles: number,
    exportPath: string,
    format: ExportFormat,
    columns: string[],
    sheetName: string,
  ) => SystemBinding.ExportBatchFormatted(configPath, cycles, exportPath, format, columns, sheetName),
  // 用当前内存结果行导出（不重新仿真、不占 Batch lease）。
  exportRowsFormatted: (
    columns: string[],
    rows: Array<Record<string, any>>,
    exportPath: string,
    format: ExportFormat,
    sheetName: string,
  ) => SystemBinding.ExportRowsFormatted(columns, rows, exportPath, format, sheetName),
  saveCSVFile: () => SystemBinding.SaveCSVFile(),
  saveExportFile: (format: ExportFormat) => SystemBinding.SaveExportFile(format),
  readTextFile: (path: string) => SystemBinding.ReadTextFile(path),
  writeTempYAML: (content: string) => SystemBinding.WriteTempYAML(content),
  allocateTempYAMLPath: () => SystemBinding.AllocateTempYAMLPath(),
  writeTextFile: (path: string, content: string) => SystemBinding.WriteTextFile(path, content),
  cleanupTempYAML: (path: string) => SystemBinding.CleanupTempYAML(path),
  exportCSVRows: (columns: string[], rows: Array<Record<string, any>>, exportPath: string) =>
    SystemBinding.ExportCSVRows(columns, rows, exportPath),
}

export const realtimeProjectApi = {
  listProjects: () => RealtimeProjectBinding.ListProjects(),
  createProject: (name: string) => RealtimeProjectBinding.CreateProject(name),
  openProject: (id: string) => RealtimeProjectBinding.OpenProject(id),
  deleteProject: (id: string) => RealtimeProjectBinding.DeleteProject(id),
  renameProject: (id: string, newName: string) => RealtimeProjectBinding.RenameProject(id, newName),
  addSource: (projectId: string) => RealtimeProjectBinding.AddSource(projectId),
  removeSource: (projectId: string, sourceId: string) => RealtimeProjectBinding.RemoveSource(projectId, sourceId),
  updateReplicas: (projectId: string, sourceId: string, replicas: number) =>
    RealtimeProjectBinding.UpdateReplicas(projectId, sourceId, replicas),
  validateProject: (projectId: string) => RealtimeProjectBinding.ValidateProject(projectId),
  compileProject: (projectId: string, outputPath: string) =>
    RealtimeProjectBinding.CompileProject(projectId, outputPath),
  listAlarmRules: (projectId: string) => RealtimeProjectBinding.ListAlarmRules(projectId),
  createAlarmRule: (projectId: string, rule: any) => RealtimeProjectBinding.CreateAlarmRule(projectId, rule),
  updateAlarmRule: (projectId: string, rule: any) => RealtimeProjectBinding.UpdateAlarmRule(projectId, rule),
  deleteAlarmRule: (projectId: string, alarmId: string) =>
    RealtimeProjectBinding.DeleteAlarmRule(projectId, alarmId),
  validateAlarmRules: (projectId: string) => RealtimeProjectBinding.ValidateAlarmRules(projectId),
  getDashboard: (projectId: string) => RealtimeProjectBinding.GetDashboard(projectId),
  saveDashboard: (projectId: string, dashboard: any) =>
    RealtimeProjectBinding.SaveDashboard(projectId, dashboard),
  setForce: (apiHost: string, apiPort: number, tag: string, mode: string, value?: number, duration?: number) =>
    RealtimeProjectBinding.SetForce(apiHost, apiPort, tag, mode, value ?? null, duration ?? null),
  clearForce: (apiHost: string, apiPort: number, tag: string) =>
    RealtimeProjectBinding.ClearForce(apiHost, apiPort, tag),
  clearAllForces: (apiHost: string, apiPort: number) =>
    RealtimeProjectBinding.ClearAllForces(apiHost, apiPort),
  getForces: (apiHost: string, apiPort: number) =>
    RealtimeProjectBinding.GetForces(apiHost, apiPort),
}

export const realtimeRuntimeApi = {
  startProject: (projectId: string, options: any) =>
    RealtimeRuntimeBinding.StartProject(projectId, options),
  startSingleYAML: (configPath: string, options: any) =>
    RealtimeRuntimeBinding.StartSingleYAML(configPath, options),
  stop: () => RealtimeRuntimeBinding.Stop(),
  getSession: () => RealtimeRuntimeBinding.GetSession(),
  getProjectRevision: (projectId: string) => RealtimeRuntimeBinding.GetProjectRevision(projectId),
  getAlarms: () => RealtimeRuntimeBinding.GetAlarms(),
  getAlarmEvents: (limit: number) => RealtimeRuntimeBinding.GetAlarmEvents(limit),
  ackAlarm: (alarmId: string) => RealtimeRuntimeBinding.AckAlarm(alarmId),
  ackAllAlarms: () => RealtimeRuntimeBinding.AckAllAlarms(),
  listRunHistory: () => RealtimeRuntimeBinding.ListRunHistory(),
  deleteRunHistory: (sessionId: string) => RealtimeRuntimeBinding.DeleteRunHistory(sessionId),
}
