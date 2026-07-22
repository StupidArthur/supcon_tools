/**
 * Materialize current YAML editor text to a temp file for offline simulation.
 * Does not touch user files or second-order tank template store.
 */
import { systemApi } from '../../lib/api'
import { useDslProjectStore } from './useDslProjectStore'
import { useGenericSimStore } from './useGenericSimStore'

/** Returns absolute path of a temp YAML written from the current editor buffer. */
export async function materializeYamlTextToTemp(): Promise<string> {
  const text = useDslProjectStore.getState().yamlText
  if (!text.trim()) {
    throw new Error('YAML 内容为空，无法启动仿真')
  }
  const path = await systemApi.writeTempYAML(text)
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
