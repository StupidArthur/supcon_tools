/**
 * Offline simulation runner panel — yamlText → temp YAML → RunBatch.
 */
import { systemApi } from '../../lib/api'
import { useCanvasStore } from '../../store/useCanvasStore'
import { cleanupTempYAML, materializeYamlTextToTemp } from './materializeYamlDraft'
import { useDslProjectStore } from './useDslProjectStore'
import { DEFAULT_OFFLINE_SIM_CYCLES, useGenericSimStore } from './useGenericSimStore'

export function SimControlPanel() {
  const yamlText = useDslProjectStore((s) => s.yamlText)
  const dfRunning = useCanvasStore((s) => s.dfStatus.running)

  const status = useGenericSimStore((s) => s.status)
  const cycles = useGenericSimStore((s) => s.cycles)
  const completedCycles = useGenericSimStore((s) => s.completedCycles)
  const error = useGenericSimStore((s) => s.error)
  const setCycles = useGenericSimStore((s) => s.setCycles)
  const beginRun = useGenericSimStore((s) => s.beginRun)
  const succeed = useGenericSimStore((s) => s.succeed)
  const fail = useGenericSimStore((s) => s.fail)

  const running = status === 'running'
  const canStart = !running && !dfRunning && Boolean(yamlText.trim())

  const handleStart = async () => {
    if (dfRunning) {
      fail('实时运行进行中，禁止启动离线仿真')
      return
    }
    if (!yamlText.trim()) {
      fail('YAML 内容为空，无法启动仿真')
      return
    }

    const n = cycles > 0 ? cycles : DEFAULT_OFFLINE_SIM_CYCLES
    beginRun(n)

    let tempPath: string | null = null
    try {
      // Ensure DataFactory.exe is resolved (no UI for path).
      const exe = await systemApi.getDataFactoryPath()
      if (exe) {
        useCanvasStore.getState().setDfPath(exe)
      }

      tempPath = await materializeYamlTextToTemp()
      const result = await systemApi.runBatch(tempPath, n)
      const columns = (result as any).columns || []
      const rows = ((result as any).rows || []) as Array<Record<string, unknown>>
      succeed({
        columns,
        rows,
        completedCycles: rows.length,
      })
    } catch (err: any) {
      fail(err?.message || String(err))
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
        cycle_time 使用 YAML 内配置。
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
          状态：{statusLabel(status)}
          {status === 'success' ? ` · 完成 ${completedCycles} 周期` : ''}
          {dfRunning ? ' · 实时运行占用中' : ''}
        </div>
      </div>

      {error ? (
        <div className="whitespace-pre-wrap break-all text-destructive" data-testid="sim-error">
          {error}
        </div>
      ) : null}
    </div>
  )
}

function statusLabel(status: string): string {
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
