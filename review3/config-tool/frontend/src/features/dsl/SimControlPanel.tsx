/**
 * Offline simulation runner panel — yamlText → temp YAML → RunBatch.
 * Results are bound to the current projectId / runId.
 */
import { useState } from 'react'
import { systemApi } from '../../lib/api'
import { useCanvasStore } from '../../store/useCanvasStore'
import { cleanupTempYAML, materializeYamlTextToTemp } from './materializeYamlDraft'
import { useDslProjectStore } from './useDslProjectStore'
import {
  DEFAULT_OFFLINE_SIM_CYCLES,
  hashYamlText,
  useGenericSimStore,
} from './useGenericSimStore'

export function SimControlPanel() {
  const yamlText = useDslProjectStore((s) => s.yamlText)
  const projectId = useDslProjectStore((s) => s.projectId)
  const dfRunning = useCanvasStore((s) => s.dfStatus.running)

  const status = useGenericSimStore((s) => s.status)
  const cycles = useGenericSimStore((s) => s.cycles)
  const completedCycles = useGenericSimStore((s) => s.completedCycles)
  const error = useGenericSimStore((s) => s.error)
  const stale = useGenericSimStore((s) => s.stale)
  const boundProjectId = useGenericSimStore((s) => s.boundProjectId)
  const setCycles = useGenericSimStore((s) => s.setCycles)
  const beginRun = useGenericSimStore((s) => s.beginRun)
  const succeed = useGenericSimStore((s) => s.succeed)
  const fail = useGenericSimStore((s) => s.fail)

  const [preflightError, setPreflightError] = useState<string | null>(null)

  const running = status === 'running' && boundProjectId === projectId
  const canStart = !running && !dfRunning && Boolean(yamlText.trim())
  const displayError =
    preflightError || (boundProjectId === projectId ? error : null)

  const handleStart = async () => {
    setPreflightError(null)
    if (dfRunning) {
      setPreflightError('实时运行进行中，禁止启动离线仿真')
      return
    }
    if (!yamlText.trim()) {
      setPreflightError('YAML 内容为空，无法启动仿真')
      return
    }

    const n = cycles > 0 ? cycles : DEFAULT_OFFLINE_SIM_CYCLES
    const epoch = useGenericSimStore.getState().epoch
    const yamlHash = hashYamlText(yamlText)
    const runId = beginRun({ projectId, yamlHash, cycles: n, epoch })

    let tempPath: string | null = null
    try {
      const exe = await systemApi.getDataFactoryPath()
      if (exe) {
        useCanvasStore.getState().setDfPath(exe)
      }

      tempPath = await materializeYamlTextToTemp()
      const result = await systemApi.runBatch(tempPath, n)
      const columns = (result as any).columns || []
      const rows = ((result as any).rows || []) as Array<Record<string, unknown>>
      succeed({
        projectId,
        runId,
        epoch,
        columns,
        rows,
        completedCycles: rows.length,
      })
    } catch (err: any) {
      fail({
        projectId,
        runId,
        epoch,
        error: err?.message || String(err),
      })
    } finally {
      await cleanupTempYAML(tempPath)
      useGenericSimStore.setState({ lastTempPath: null })
    }
  }

  return (
    <div className="space-y-3 p-3 text-xs" data-testid="sim-control-panel">
      <div className="font-medium">仿真运行</div>
      <p className="text-muted-foreground">
        离线数据生成：将当前 YAML 草稿写入临时文件并调用 Batch，不启动 OPC UA / 实时实例，不覆盖用户文件。
        cycle_time 使用 YAML 内配置。结果绑定当前工程会话。
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="text-muted-foreground">仿真周期数</span>
          <input
            type="number"
            min={1}
            value={cycles}
            disabled={running}
            onChange={(e) => setCycles(Number(e.target.value))}
            className="block w-28 rounded-md border border-border bg-card px-2 py-1"
            data-testid="sim-cycles"
          />
        </label>
        <button
          type="button"
          onClick={() => void handleStart()}
          disabled={!canStart}
          className="rounded-md bg-green-600 px-3 py-1.5 text-white disabled:opacity-40"
          data-testid="sim-start-button"
        >
          {running ? '仿真中…' : '开始仿真'}
        </button>
        <div data-testid="sim-status">
          状态：{statusLabel(status, boundProjectId === projectId)}
          {status === 'success' && boundProjectId === projectId
            ? ` · 完成 ${completedCycles} 周期`
            : ''}
          {stale && boundProjectId === projectId ? ' · 结果已过期' : ''}
          {dfRunning ? ' · 实时运行占用中' : ''}
        </div>
      </div>

      {displayError ? (
        <div className="whitespace-pre-wrap break-all text-destructive" data-testid="sim-error">
          {displayError}
        </div>
      ) : null}
    </div>
  )
}

function statusLabel(status: string, owned: boolean): string {
  if (!owned && status !== 'idle') return '空闲'
  switch (status) {
    case 'idle':
      return '空闲'
    case 'running':
      return '运行中'
    case 'success':
      return '成功'
    case 'failed':
      return '失败'
    default:
      return status
  }
}
