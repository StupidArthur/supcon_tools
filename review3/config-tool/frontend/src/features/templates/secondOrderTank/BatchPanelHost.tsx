/**
 * Host wiring BatchPanel to SystemBinding + template/runtime state.
 *
 * 批量仿真结果本地化改造：异步启动 + 轮询状态 + 预览行。
 */
import { useCallback, useRef, useState } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { systemApi } from '../../../lib/api'
import { canStartBatch } from '../batchState'
import { BatchPanel } from './BatchPanel'
import { downsample, type TrendPoint } from '../../runtime/trendBuffer'

const DEFAULT_BATCH_CYCLES = 2000
const MAX_TREND_POINTS = 3000
const POLL_INTERVAL_MS = 800
const PREVIEW_LIMIT = 500

function rowsToTrendPoints(rows: Array<Record<string, unknown>>): TrendPoint[] {
  return rows.map((row, idx) => {
    const simTime =
      typeof row._sim_time === 'number'
        ? row._sim_time
        : typeof row.sim_time === 'number'
          ? row.sim_time
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
  const [batchId, setBatchId] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const dirty = dirtyPaths.size > 0
  const valid = validationErrors.length === 0
  const allowed = canStartBatch({
    dirty,
    valid,
    runtimeState: status === 'running' ? 'BATCH_RUNNING' : runtimeState,
  })

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

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
      setProgress(0.1)
      const result = await systemApi.runBatch(sourcePath, cycles, 0, 0, 0)
      const bid = result.batchId
      if (!bid) throw new Error('后端未返回 batchId')
      setBatchId(bid)
      setProgress(0.2)

      // 轮询状态
      await new Promise<void>((resolve, reject) => {
        pollRef.current = setInterval(async () => {
          try {
            const st = await systemApi.getBatchStatus(bid)
            const pct = st.cyclesRequested > 0
              ? Math.min(0.9, 0.2 + 0.7 * (st.cyclesCompleted / st.cyclesRequested))
              : 0.2
            setProgress(pct)

            if (st.status === 'completed') {
              stopPolling()
              setProgress(1)
              // 加载预览行
              const rowsResp = await systemApi.getBatchRows(bid, 0, PREVIEW_LIMIT)
              const rows = (rowsResp.rows ?? []) as Array<Record<string, unknown>>
              const points = downsample(rowsToTrendPoints(rows), MAX_TREND_POINTS)
              setResultPoints(
                points.map((p) => ({
                  _cycle: p.cycleCount,
                  sim_time: p.simTime,
                  ...p.values,
                })),
              )
              setStatus('success')
              setRuntimeState('STOPPED_EDITING')
              resolve()
            } else if (st.status === 'failed' || st.status === 'cancelled' || st.status === 'interrupted') {
              stopPolling()
              setStatus('failed')
              setError(st.error || `任务${st.status}`)
              setProgress(0)
              setRuntimeState('STOPPED_EDITING')
              resolve()
            }
          } catch (pollErr: any) {
            // 轮询失败不立即终止
          }
        }, POLL_INTERVAL_MS)
      })
    } catch (err) {
      stopPolling()
      setStatus('failed')
      setError(err instanceof Error ? err.message : String(err))
      setResultPoints([])
      setProgress(0)
      setRuntimeState('STOPPED_EDITING')
    }
  }, [allowed, sourcePath, cycles, setRuntimeState, stopPolling])

  const onExport = useCallback(async () => {
    if (!sourcePath || status === 'failed' || !batchId) return
    try {
      const path = await systemApi.saveCSVFile()
      if (!path) return
      await systemApi.exportBatchResult(batchId, [], path, 'csv', '')
      setLastCsvHint(path)
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [sourcePath, batchId, status])

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
