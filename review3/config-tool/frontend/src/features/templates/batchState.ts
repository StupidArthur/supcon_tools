/**
 * Batch vs realtime gating helpers (stage 7).
 * No relative imports — loaded via file:// prospective import.
 */

export type BatchGateState = {
  dirty?: boolean
  valid?: boolean
  runtimeState?: string
}

/** Whether Batch may start from the given workspace state. */
export function canStartBatch(state: BatchGateState): boolean {
  if (state.dirty) return false
  if (state.valid === false) return false
  const rs = state.runtimeState || ''
  if (
    rs === 'SIMULATION_RUNNING' ||
    rs === 'REALTIME_RUNNING' ||
    rs === 'BATCH_RUNNING' ||
    rs === 'STARTING' ||
    rs === 'STOPPING'
  ) {
    return false
  }
  return rs === 'STOPPED_EDITING'
}

/** Whether realtime Start is allowed (blocked while batch runs). */
export function canStartRealtime(state: BatchGateState): boolean {
  const rs = state.runtimeState || ''
  return rs !== 'BATCH_RUNNING'
}
