// API 封装层：所有后端调用经此统一封装，组件只 import { api }。
// v2 多集群：方法带 clusterID 参数。
import {
  StartAll, StopAll, StartCluster, StopCluster,
  ListClusterIDs,
  GetClusterStatus, GetPerf, GetGlobalPerf,
  GetSnapshot, GetNodes, GetWorkers, GetActors, GetJobs,
  GetNodeHistory, GetActorEvents, GetJobHistory,
  GetConfig, SaveConfig, AddCluster, RemoveCluster, UpdateCluster,
  ListAlerts, AckAlert, CountAlerts,
  OpenInFolder, GetLogPath, GetDBPath,
} from '../../wailsjs/go/main/App'
import type { model, config, collector, main } from '../../wailsjs/go/models'

export type CollectorStatus = model.CollectorStatus
export type PerfMetrics = model.PerfMetrics
export type GlobalPerf = model.GlobalPerf
export type Snapshot = collector.Snapshot
export type ClusterMetric = model.ClusterMetric
export type NodeMetric = model.NodeMetric
export type WorkerSnapshot = model.WorkerSnapshot
export type ActorSnapshot = model.ActorSnapshot
export type JobSnapshot = model.JobSnapshot
export type ActorEvent = model.ActorEvent
export type Alert = model.Alert
export type HistoryRange = main.HistoryRange
export type SaveConfigResult = main.SaveConfigResult

// Config/ClusterConfig/Thresholds 用纯 interface（剥离 Wails 生成的 convertValues 方法），
// 便于前端用对象字面量构造与 setState。
export interface Thresholds {
  nodeCpu: number
  nodeMem: number
  nodeGpu: number
  workerCpu: number
  workerMem: number
  workerGpu: number
}
export interface ClusterConfig {
  id: string
  platformUrl: string
}
export interface Config {
  clusters: ClusterConfig[]
  dbPath: string
  logDir: string
  sortBy: string
  sampleEvery: number
  thresholds: Thresholds
  // 以下后端用，前端不展示（可选）
  timeoutSec?: number
  concurrency?: number
  globalConcurrency?: number
  recoverConsecutive?: number
}

export const api = {
  startAll: StartAll,
  stopAll: StopAll,
  startCluster: StartCluster,
  stopCluster: StopCluster,
  listClusterIDs: ListClusterIDs,
  getClusterStatus: GetClusterStatus,
  getPerf: GetPerf,
  getGlobalPerf: GetGlobalPerf,
  getSnapshot: GetSnapshot,
  getNodes: GetNodes,
  getWorkers: GetWorkers,
  getActors: GetActors,
  getJobs: GetJobs,
  getNodeHistory: GetNodeHistory,
  getActorEvents: GetActorEvents,
  getJobHistory: GetJobHistory,
  getConfig: GetConfig as () => Promise<Config>,
  saveConfig: SaveConfig as (cfg: Config) => Promise<SaveConfigResult>,
  addCluster: AddCluster as (cl: ClusterConfig) => Promise<SaveConfigResult>,
  removeCluster: RemoveCluster,
  updateCluster: UpdateCluster as (cl: ClusterConfig) => Promise<SaveConfigResult>,
  listAlerts: ListAlerts,
  ackAlert: AckAlert,
  countAlerts: CountAlerts,
  openInFolder: OpenInFolder,
  getLogPath: GetLogPath,
  getDBPath: GetDBPath,
}
