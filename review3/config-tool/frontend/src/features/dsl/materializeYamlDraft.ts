/**
 * Materialize a fixed YAML snapshot to a temp file for offline simulation.
 * Does not read from the DSL store — caller must pass the snapshot explicitly.
 */
import { systemApi } from '../../lib/api'
import { useDslProjectStore } from './useDslProjectStore'
import { useGenericSimStore } from './useGenericSimStore'

/**
 * Writes `yamlSnapshot` to a unique temp YAML and returns its absolute path.
 */
export async function materializeYamlTextToTemp(yamlSnapshot: string): Promise<string> {
  if (!yamlSnapshot.trim()) {
    throw new Error('YAML 内容为空，无法启动仿真')
  }
  const path = await systemApi.writeTempYAML(yamlSnapshot)
  useDslProjectStore.getState().setLastDraftSimPath(path)
  useGenericSimStore.setState({ lastTempPath: path })
  return path
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
