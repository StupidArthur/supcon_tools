import { GetTeams } from "../../wailsjs/go/bindings/TeamBinding"
import { GetRanking } from "../../wailsjs/go/bindings/RankingBinding"
import { GetEvalConfig, UpdateEvalConfig } from "../../wailsjs/go/bindings/BatchBinding"
import { GetPersonalList, GetTenantDetail, CleanupTenant } from "../../wailsjs/go/bindings/PersonalBinding"
import { ScanMonitor, GetMonitorSnapshot, ConfirmAbnormal } from "../../wailsjs/go/bindings/MonitorBinding"
import type { batch, monitor, personal, ranking, team } from "../../wailsjs/go/models"

export type Team = team.Team
export type RankingItem = ranking.Item
export type EvalConfig = batch.EvalConfig
export type UpdateResult = batch.UpdateResult
export type PersonalRow = personal.Row
export type TenantDetail = personal.Detail
export type CleanupResult = personal.CleanupResult
export type MonitorReport = monitor.Report

// 子异常状态。
export interface SubAbnormal {
  active: boolean
  since: string
  detail: string
}

// 事件快照类型（非 bound 方法签名，Wails 不生成，故本地定义）。
export interface MonitorReportLite {
  name: string
  tenantId: string
  dsName: string
  dsTarUrl: string
  dsFound: boolean
  dsAlive: boolean
  tagTotal: number
  tagGood: number
  badTags: string[]
  error: string
  sampleValue: string
  sampleTime: string

  subAPIFailure: SubAbnormal
  subDsNotFound: SubAbnormal
  subDsOffline: SubAbnormal
  subTagBad: SubAbnormal
  subValueStale: SubAbnormal

  abnormal: boolean

  lastAbnType: number
  lastAbnSince: string
  lastAbnDetail: string
  lastAbnConfirmed: boolean
}
export interface MonitorCycle {
  at: string
  durMs: number
  skipped: boolean
  reports: MonitorReportLite[]
}
export interface MonitorSnapshot {
  cycle: MonitorCycle
}

export const teamApi = {
  list: (): Promise<Team[]> => GetTeams(),
}

export const rankingApi = {
  fetch: (): Promise<RankingItem[]> => GetRanking(),
}

export const batchApi = {
  getEvalConfig: (): Promise<EvalConfig> => GetEvalConfig(),
  updateEvalConfig: (pracLoadEnabled: number, examLoadEnabled: number, evalDurationMinutes: number): Promise<UpdateResult> =>
    UpdateEvalConfig(pracLoadEnabled, examLoadEnabled, evalDurationMinutes),
}

export const personalApi = {
  list: (): Promise<PersonalRow[]> => GetPersonalList(),
  detail: (tenantId: string): Promise<TenantDetail> => GetTenantDetail(tenantId),
  cleanup: (tenantId: string): Promise<CleanupResult> => CleanupTenant(tenantId),
}

export const monitorApi = {
  scan: (): Promise<MonitorReport> => ScanMonitor(),
  snapshot: (): Promise<MonitorSnapshot | null> => GetMonitorSnapshot(),
  confirm: (tenantId: string): Promise<void> => ConfirmAbnormal(tenantId),
}
