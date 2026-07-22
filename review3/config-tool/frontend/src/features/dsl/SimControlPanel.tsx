/**
 * DSL 仿真控制：用当前有效 draft 物化到临时 YAML 后启动（不覆盖用户文件）。
 */
import { useRef, useState } from 'react'
import { systemApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { canStartRealtime } from '../templates/batchState'
import { useTemplateStore } from '../templates/useTemplateStore'
import { materializeDraftToTemp } from './materializeDraft'
import { useDslProjectStore } from './useDslProjectStore'

export function SimControlPanel() {
  const projectKind = useDslProjectStore((s) => s.projectKind)
  const lastDraftSimPath = useDslProjectStore((s) => s.lastDraftSimPath)
  const yamlError = useDslProjectStore((s) => s.yamlError)
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const setRuntimeState = useTemplateStore((s) => s.setRuntimeState)
  const setRunningIdentity = useTemplateStore((s) => s.setRunningIdentity)
  const draft = useTemplateStore((s) => s.draft)

  const runtimeConnect = useRuntimeStore((s) => s.connect)
  const runtimeDisconnect = useRuntimeStore((s) => s.disconnect)
  const rotatePreviousRun = useRuntimeStore((s) => s.rotatePreviousRun)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const stale = useRuntimeStore((s) => s.stale)

  const [error, setError] = useState<string | null>(null)
  const [cycleTime, setCycleTime] = useState(0.5)
  const operationIdRef = useRef(0)

  const isRunning = runtimeState === 'SIMULATION_RUNNING' || runtimeState === 'REALTIME_RUNNING'
  const isStarting = runtimeState === 'STARTING'
  const isStopping = runtimeState === 'STOPPING'
  const hasErrors =
    (projectKind === 'template' && validationErrors.length > 0) ||
    (projectKind === 'generic' && Boolean(yamlError))

  const handleStart = async () => {
    setError(null)
    if (!canStartRealtime({ runtimeState })) {
      setError('批量任务正在运行，无法启动仿真')
      return
    }
    if (hasErrors) {
      setError('校验失败，禁止启动')
      return
    }
    const myOperationId = ++operationIdRef.current
    setRuntimeState('STARTING')
    try {
      rotatePreviousRun?.()
      const tempPath = await materializeDraftToTemp()
      const ct = draft?.cycleTime || cycleTime || 0.5
      await systemApi.start({
        configPath: tempPath,
        mode: 'REALTIME',
        cycleTime: ct,
        port: 18951,
        apiHost: '127.0.0.1',
        apiPort: 8000,
        runtimeName: 'second_order_tank',
        enableOpcUa: true,
      })
      if (myOperationId !== operationIdRef.current) return
      const status = await systemApi.status()
      if (myOperationId !== operationIdRef.current) return
      if (!status.running || !status.apiReady || !status.configPath || !status.configHash || !status.startedAt) {
        throw new Error('后端状态不完整')
      }
      setRunningIdentity({
        path: status.configPath,
        contentHash: status.configHash,
        startedAt: status.startedAt,
      })
      try {
        await runtimeConnect()
      } catch (wsErr) {
        console.warn('runtime connect failed:', wsErr)
      }
      setRuntimeState('SIMULATION_RUNNING')
    } catch (err: any) {
      if (myOperationId !== operationIdRef.current) return
      setError(err?.message || String(err))
      setRuntimeState('ERROR')
      setRunningIdentity(null)
    }
  }

  const handleStop = async () => {
    if (isStopping) return
    operationIdRef.current++
    setRuntimeState('STOPPING')
    try {
      runtimeDisconnect()
      await systemApi.stop()
      setRuntimeState('STOPPED_EDITING')
      setRunningIdentity(null)
    } catch (err: any) {
      setError(err?.message || String(err))
      setRuntimeState('ERROR')
    }
  }

  return (
    <div className="space-y-3 p-3 text-xs" data-testid="sim-control-panel">
      <div className="font-medium">仿真控制</div>
      <p className="text-muted-foreground">
        使用当前有效 draft 启动：校验通过后写入临时 YAML，不覆盖用户文件；继续编辑不影响已启动实例。
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="text-muted-foreground">周期 (秒)</span>
          <input
            type="number"
            step={0.1}
            min={0.01}
            value={draft?.cycleTime ?? cycleTime}
            onChange={(e) => setCycleTime(Number(e.target.value))}
            disabled={isRunning || isStarting}
            className="block w-24 rounded-md border border-border bg-card px-2 py-1"
            data-testid="sim-cycle-time"
          />
        </label>
        {!isRunning && !isStarting && !isStopping ? (
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={hasErrors || !canStartRealtime({ runtimeState })}
            className="rounded-md bg-green-600 px-3 py-1.5 text-white disabled:opacity-40"
            data-testid="sim-start-button"
          >
            启动仿真
          </button>
        ) : null}
        {(isRunning || isStarting) && !isStopping ? (
          <button
            type="button"
            onClick={() => void handleStop()}
            className="rounded-md bg-destructive px-3 py-1.5 text-destructive-foreground"
            data-testid="sim-stop-button"
          >
            停止
          </button>
        ) : null}
        <div data-testid="sim-status">
          状态：{runtimeState}
          {isRunning ? ` · 连接 ${connectionState}${stale ? ' (stale)' : ''}` : ''}
        </div>
      </div>
      {lastDraftSimPath ? (
        <div className="truncate text-muted-foreground" title={lastDraftSimPath}>
          临时配置：{lastDraftSimPath}
        </div>
      ) : null}
      {error ? (
        <div className="text-destructive" data-testid="sim-error">
          {error}
        </div>
      ) : null}
    </div>
  )
}
