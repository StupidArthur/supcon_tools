// Wails JS bindings - 纯 JS 实现

export function BrowseDir(title) {
  return window['go']['bindings']['DebugBinding']['BrowseDir'](title)
}

export function BrowseExe() {
  return window['go']['bindings']['DebugBinding']['BrowseExe']()
}

export function BrowseYAML() {
  return window['go']['bindings']['DebugBinding']['BrowseYAML']()
}

export function SaveCSVFile() {
  return window['go']['bindings']['DebugBinding']['SaveCSVFile']()
}

export function ListConfigs(workDir) {
  return window['go']['bindings']['DebugBinding']['ListConfigs'](workDir)
}

export function ParseYAMLConfig(yamlPath) {
  return window['go']['bindings']['DebugBinding']['ParseYAMLConfig'](yamlPath)
}

export function StartEngine(params) {
  return window['go']['bindings']['DebugBinding']['StartEngine'](params)
}

export function StartBatch(params) {
  return window['go']['bindings']['DebugBinding']['StartBatch'](params)
}

export function ReadBatchResult(csvPath) {
  return window['go']['bindings']['DebugBinding']['ReadBatchResult'](csvPath)
}

export function ExportBatch(params, exportPath) {
  return window['go']['bindings']['DebugBinding']['ExportBatch'](params, exportPath)
}

export function StopEngine() {
  return window['go']['bindings']['DebugBinding']['StopEngine']()
}

export function GetStatus() {
  return window['go']['bindings']['DebugBinding']['GetStatus']()
}

export function CleanupTempFile(path) {
  return window['go']['bindings']['DebugBinding']['CleanupTempFile'](path)
}
