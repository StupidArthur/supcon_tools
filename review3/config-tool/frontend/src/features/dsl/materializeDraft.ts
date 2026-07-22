/**
 * Materialize current DSL draft to a temp YAML for simulation (no user-file overwrite).
 */
import { systemApi, templateApi } from '../../lib/api'
import { useTemplateStore } from '../templates/useTemplateStore'
import { useDslProjectStore } from './useDslProjectStore'

/**
 * Writes the effective draft to a unique temp YAML and returns its absolute path.
 * Does not mutate the user's source file or template store identity.
 */
export async function materializeDraftToTemp(): Promise<string> {
  const dsl = useDslProjectStore.getState()
  const kind = dsl.projectKind

  if (kind === 'generic') {
    const text = dsl.yamlText
    if (!text.trim()) {
      throw new Error('YAML 内容为空，无法启动仿真')
    }
    if (dsl.yamlError) {
      throw new Error(dsl.yamlError)
    }
    const path = await systemApi.writeTempYAML(text)
    useDslProjectStore.getState().setLastDraftSimPath(path)
    return path
  }

  // template / second-order tank
  const state = useTemplateStore.getState()
  if (!state.sourcePath || !state.savedContentHash || !state.draft || !state.saved) {
    throw new Error('模板尚未加载，无法启动仿真')
  }
  if (state.validationErrors.length > 0) {
    throw new Error('校验失败，禁止启动仿真')
  }

  const tempPath = await systemApi.allocateTempYAMLPath()
  // Call binding directly so store.sourcePath stays on the user file.
  const patches: Array<{ path: string; value: number }> = []
  const saved = state.saved
  const draft = state.draft
  if (saved.cycleTime !== draft.cycleTime) patches.push({ path: 'cycleTime', value: draft.cycleTime })
  if (saved.sourceFlow !== draft.sourceFlow) patches.push({ path: 'sourceFlow', value: draft.sourceFlow })
  for (const k of Object.keys(saved.valve) as Array<keyof typeof saved.valve>) {
    if (saved.valve[k] !== draft.valve[k]) patches.push({ path: `valve.${k}`, value: draft.valve[k] as number })
  }
  for (const k of Object.keys(saved.tank1) as Array<keyof typeof saved.tank1>) {
    if (saved.tank1[k] !== draft.tank1[k]) patches.push({ path: `tank1.${k}`, value: draft.tank1[k] as number })
  }
  for (const k of Object.keys(saved.tank2) as Array<keyof typeof saved.tank2>) {
    if (saved.tank2[k] !== draft.tank2[k]) patches.push({ path: `tank2.${k}`, value: draft.tank2[k] as number })
  }
  for (const k of ['PB', 'TI', 'TD', 'KF', 'SV', 'highLimit', 'lowLimit', 'deadband', 'MV', 'MODE'] as const) {
    const a = (saved.pid as any)[k]
    const b = (draft.pid as any)[k]
    if (a !== b && typeof b === 'number') {
      patches.push({ path: `pid.${k}`, value: b })
    }
  }

  await templateApi.save({
    sourcePath: state.sourcePath,
    targetPath: tempPath,
    expectedHash: state.savedContentHash,
    allowOverwrite: true,
    patches,
  })
  useDslProjectStore.getState().setLastDraftSimPath(tempPath)
  return tempPath
}
