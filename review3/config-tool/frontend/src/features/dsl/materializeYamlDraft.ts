/**
 * Materialize a fixed YAML snapshot to a temp file for offline simulation.
 * Does not read from the DSL store — caller must pass the snapshot explicitly.
 *
 * 只负责「校验 + writeTempYAML + 返回路径」。临时路径属于发起任务的局部变量，
 * 由调用方在 finally 中用 cleanupTempYAML 清理；本函数不向任何全局 Store 写入路径。
 */
import { systemApi } from '../../lib/api'

/**
 * Writes `yamlSnapshot` to a unique temp YAML and returns its absolute path.
 */
export async function materializeYamlTextToTemp(yamlSnapshot: string): Promise<string> {
  if (!yamlSnapshot.trim()) {
    throw new Error('YAML 内容为空，无法启动仿真')
  }
  return await systemApi.writeTempYAML(yamlSnapshot)
}

/** Best-effort cleanup of draft-sim temp directory. */
export async function cleanupTempYAML(path: string | null | undefined): Promise<void> {
  if (!path) return
  try {
    await systemApi.cleanupTempYAML(path)
  } catch (err) {
    console.warn('cleanupTempYAML:', err)
  }
}
