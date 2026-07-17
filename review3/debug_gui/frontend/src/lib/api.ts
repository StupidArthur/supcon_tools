import type { YAMLConfig, BatchResult, EngineStatus } from '../types'

import {
  BrowseDir, BrowseExe, BrowseYAML, SaveCSVFile,
  ListConfigs, ParseYAMLConfig,
  StartEngine, StartBatch, ReadBatchResult, ExportBatch,
  StopEngine, GetStatus, CleanupTempFile,
} from '../../wailsjs/go/bindings/DebugBinding'

export const debugApi = {
  browseDir: BrowseDir,
  browseExe: BrowseExe,
  browseYAML: BrowseYAML,
  saveCSVFile: SaveCSVFile,

  listConfigs: ListConfigs,
  parseYAMLConfig: ParseYAMLConfig,

  startEngine: StartEngine,
  startBatch: StartBatch,
  readBatchResult: ReadBatchResult,
  exportBatch: ExportBatch,

  stopEngine: StopEngine,
  getStatus: GetStatus,
  cleanupTempFile: CleanupTempFile,
}

export type { YAMLConfig, BatchResult, EngineStatus }
