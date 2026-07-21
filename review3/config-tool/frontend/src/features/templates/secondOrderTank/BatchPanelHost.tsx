/**
 * Host wiring BatchPanel to SystemBinding + template/runtime state (stage 7/8).
 */
import { useCallback, useState } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { systemApi } from '../../../lib/api'
import { canStartBatch } from '../batchState'
import { BatchPanel } from './BatchPanel'
import { downsample, type TrendPoint } from '../../runtime/trendBuffer'

const DEFAULT_BATCH_CYCLES = 2000
const MAX_TREND_POINTS = 3000

function rowsToTrendPoints(rows: Array<Record<string, unknown>>): TrendPoint[] {
  return rows.map((row, idx) => {
    const simTime =
      typeof row.sim_time === 'number'
        ? row.sim_time
        : typeof row.t === 'number'
          ? row.t
          : idx
    const cycleCount = typeof row._cycle === 'number' ? row._cycle : idx
    const values: Record<string, number | null> = {}
    for (const [k, v] of Object.entries(row)) {
      if (typeof v === 'number' && Number.isFinite(v)) {
        values[k] = v
      }
    }
    return { cycleCount, simTime, values }
  })
}

export function BatchPanelHost() {
  const dirtyPaths = useTemplateStore((s) => s.dirtyPaths)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const sourcePath = useTemplateStore((s) => s.sourcePath)
  const setRuntimeState = useTemplateStore((s) => s.setRuntimeState)

  const [cycles, setCycles] = useState(DEFAULT_BATCH_CYCLES)
  const [status, setStatus] = useState<'idle' | 'running' | 'success' | 'failed'>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [resultPoints, setResultPoints] = useState<Array<Record<string, unknown>>>([])
  const [lastCsvHint, setLastCsvHint] = useState('')

  const dirty = dirtyPaths.size > 0
  const valid = validationErrors.length === 0
  const allowed = canStartBatch({
    dirty,
    valid,
    runtimeState: status === 'running' ? 'BATCH_RUNNING' : runtimeState,
  })

  const onStart = useCallback(async () => {
    if (!allowed || !sourcePath) {
      setStatus('failed')
      setError(!sourcePath ? '没有可运行的配置路径' : '当前状态不可启动 Batch')
      return
    }
    setError(null)
    setResultPoints([])
    setProgress(0.05)
    setStatus('running')
    setRuntimeState('BATCH_RUNNING')
    try {
      setProgress(0.2)
      const result = await systemApi.runBatch(sourcePath, cycles)
      setProgress(0.8)
      const points = downsample(rowsToTrendPoints(result.rows || []), MAX_TREND_POINTS)
      setResultPoints(
        points.map((p) => ({
          _cycle: p.cycleCount,
          sim_time: p.simTime,
          ...p.values,
        })),
      )
      setProgress(1)
      setStatus('success')
      setRuntimeState('STOPPED_EDITING')
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : String(err))
      setResultPoints([])
      setProgress(0)
      setRuntimeState('STOPPED_EDITING')
    }
  }, [allowed, sourcePath, cycles, setRuntimeState])

  const onExport = useCallback(async () => {
    if (!sourcePath || status === 'failed') return
    try {
      const path = await systemApi.saveCSVFile()
      if (!path) return
      await systemApi.exportBatch(sourcePath, cycles, path)
      setLastCsvHint(path)
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [sourcePath, cycles, status])

  return (
    <BatchPanel
      status={status === 'running' ? 'running' : status}
      error={error}
      progress={progress}
      resultPoints={resultPoints}
      exportPath={lastCsvHint}
      cycles={cycles}
      onCyclesChange={setCycles}
      onStart={onStart}
      onExport={onExport}
      defaultCycles={DEFAULT_BATCH_CYCLES}
    />
  )
}
