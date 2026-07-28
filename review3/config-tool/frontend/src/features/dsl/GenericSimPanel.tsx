/**
 * 通用离线仿真一体面板 -- 运行控制 + 列配置 + 趋势大图 + 导出 + 统计。
 *
 * 批量仿真结果本地化改造：
 * - RunBatch 异步启动，立即返回 batchId
 * - 每 800ms 轮询 GetBatchStatus，显示进度
 * - 完成后只加载最多 500 行预览数据
 * - 导出只传 batchId，由 Python 从 SQLite 流式导出
 * - 不再将完整 rows 放入 Zustand
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { systemApi } from '../../lib/api'
import { type ExportFormat } from '../../lib/exportTypes'
import { backendBatchBusy, useCanvasStore } from '../../store/useCanvasStore'
import { ExportDialog } from './ExportDialog'
import { hasPlotScale, scalePlotValue } from './plotScaling'
import {
  createExportSession,
  type ExportSession,
  isNumericColumn,
  sanitizeExportColumns,
  validateExportRowMetadata,
  validateExportSession,
} from './exportSession'
import { cleanupTempYAML, materializeYamlTextToTemp } from './materializeYamlDraft'
import { useDslProjectStore } from './useDslProjectStore'
import {
  DEFAULT_OFFLINE_SIM_CYCLES,
  hashYamlText,
  useGenericSimStore,
} from './useGenericSimStore'

const COLORS = ['#3b82f6', '#06b6d4', '#f97316', '#10b981', '#8b5cf6', '#ec4899', '#f59e0b', '#6366f1']

const POLL_INTERVAL_MS = 800
const PREVIEW_LIMIT = 500

interface ColumnStat {
  min: number
  max: number
  last: number
}

function columnStats(rows: Array<Record<string, unknown>>, col: string): ColumnStat | null {
  let min = Infinity
  let max = -Infinity
  let last: number | null = null
  for (const row of rows) {
    const v = row[col]
    if (typeof v !== 'number' || !Number.isFinite(v)) continue
    if (v < min) min = v
    if (v > max) max = v
    last = v
  }
  if (last === null) return null
  return { min, max, last }
}

function fmt(v: number): string {
  if (Math.abs(v) >= 1000 || (v !== 0 && Math.abs(v) < 0.001)) {
    return v.toExponential(2)
  }
  return Number(v.toFixed(3)).toString()
}

export function GenericSimPanel() {
  const projectId = useDslProjectStore((s) => s.projectId)
  const dfStatus = useCanvasStore((s) => s.dfStatus)
  const refreshStatus = useCanvasStore((s) => s.refreshStatus)
  const dfRunning = dfStatus.running

  const status = useGenericSimStore((s) => s.status)
  const cycles = useGenericSimStore((s) => s.cycles)
  const completedCycles = useGenericSimStore((s) => s.completedCycles)
  const error = useGenericSimStore((s) => s.error)
  const columns = useGenericSimStore((s) => s.columns)
  const previewRows = useGenericSimStore((s) => s.previewRows)
  const selectedColumns = useGenericSimStore((s) => s.selectedColumns)
  const stale = useGenericSimStore((s) => s.stale)
  const boundProjectId = useGenericSimStore((s) => s.boundProjectId)
  const setCycles = useGenericSimStore((s) => s.setCycles)
  const beginRun = useGenericSimStore((s) => s.beginRun)
  const succeed = useGenericSimStore((s) => s.succeed)
  const fail = useGenericSimStore((s) => s.fail)
  const toggleColumn = useGenericSimStore((s) => s.toggleColumn)
  const hasDisplay = useGenericSimStore((s) => s.hasDisplayResult(projectId))
  const hasExportable = useGenericSimStore((s) => s.hasExportableResult(projectId))
  const globalBatchRunning = useGenericSimStore((s) => s.globalBatchRunning)
  const boundRunId = useGenericSimStore((s) => s.boundRunId)
  const boundYamlHash = useGenericSimStore((s) => s.boundYamlHash)
  const plotScales = useGenericSimStore((s) => s.plotScales)

  const [preflightError, setPreflightError] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exportSession, setExportSession] = useState<ExportSession | null>(null)
  const [cycleTime, setCycleTime] = useState(0.5)
  const [sampleInterval, setSampleInterval] = useState(0)
  const [startTime, setStartTime] = useState(() => {
    const now = new Date()
    now.setSeconds(0, 0)
    return now.toISOString().slice(0, 16)
  })

  // 轮询控制
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const owned = boundProjectId === projectId
  const running = status === 'running' && owned
  const yamlText = useDslProjectStore((s) => s.yamlText)
  const batchBusy = globalBatchRunning || backendBatchBusy(dfStatus)
  const canStart = !running && !dfRunning && !batchBusy && Boolean(yamlText.trim())
  const displayError = preflightError || (owned ? error : null)

  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])
  useEffect(() => {
    if (!batchBusy) return
    const id = setInterval(() => refreshStatus(), 1000)
    return () => clearInterval(id)
  }, [batchBusy, refreshStatus])

  // 页面卸载时停止轮询
  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!exportSession) return
    if (
      exportSession.projectId !== projectId ||
      exportSession.runId !== boundRunId ||
      exportSession.yamlHash !== boundYamlHash
    ) {
      setExportSession(null)
      setExportOpen(false)
    }
  }, [projectId, boundRunId, boundYamlHash, exportSession])

  const numericColumns = useMemo(
    () =>
      owned && hasDisplay
        ? columns.filter((c) => c !== '_cycle' && !c.startsWith('_') && isNumericColumn(previewRows, c))
        : [],
    [columns, previewRows, owned, hasDisplay],
  )

  const chartData = useMemo(() => {
    if (!owned || !hasDisplay) return []
    return previewRows.map((row, idx) => {
      const point: Record<string, number | string> = {
        _cycle: typeof row._cycle === 'number' ? row._cycle : idx,
      }
      for (const col of selectedColumns) {
        const v = row[col]
        if (typeof v === 'number' && Number.isFinite(v)) {
          point[col] = scalePlotValue(v, plotScales[col])
        }
      }
      return point
    })
  }, [previewRows, selectedColumns, plotScales, owned, hasDisplay])

  const stats = useMemo(() => {
    if (!owned || !hasDisplay) return [] as Array<{ col: string; stat: ColumnStat }>
    return selectedColumns
      .map((col) => ({ col, stat: columnStats(previewRows, col) }))
      .filter((x): x is { col: string; stat: ColumnStat } => x.stat !== null)
  }, [previewRows, selectedColumns, owned, hasDisplay])

  const handleStart = async () => {
    setPreflightError(null)
    setExportError(null)
    const latestDf = useCanvasStore.getState().dfStatus
    if (latestDf.running) {
      setPreflightError('实时运行进行中，禁止启动离线仿真')
      return
    }
    if (useGenericSimStore.getState().globalBatchRunning || backendBatchBusy(latestDf)) {
      setPreflightError('已有批量任务正在运行，禁止启动新的离线仿真')
      return
    }
    const yamlSnapshot = useDslProjectStore.getState().yamlText
    if (!yamlSnapshot.trim()) {
      setPreflightError('YAML 内容为空，无法启动仿真')
      return
    }
    const n = cycles > 0 ? cycles : DEFAULT_OFFLINE_SIM_CYCLES
    const epoch = useGenericSimStore.getState().epoch
    const yamlHash = hashYamlText(yamlSnapshot)
    const runId = beginRun({ projectId, yamlHash, cycles: n, epoch })
    useGenericSimStore.getState().beginGlobalBatch(runId)

    let tempPath: string | null = null
    try {
      const exe = await systemApi.getDataFactoryPath()
      if (exe) {
        useCanvasStore.getState().setDfPath(exe)
      }
      tempPath = await materializeYamlTextToTemp(yamlSnapshot)
      const startTs = startTime ? new Date(startTime).getTime() / 1000 : 0
      const result = await systemApi.runBatch(tempPath, n, cycleTime, sampleInterval, startTs)
      const batchId = result.batchId
      if (!batchId) {
        throw new Error('后端未返回 batchId')
      }
      useGenericSimStore.getState().setBatchId(batchId)

      // 开始轮询
      await new Promise<void>((resolve) => {
        pollRef.current = setInterval(async () => {
          try {
            const st = await systemApi.getBatchStatus(batchId)
            useGenericSimStore.getState().pollStatus({
              completedCycles: st.cyclesCompleted ?? 0,
              cyclesRequested: st.cyclesRequested ?? 0,
            })

            if (st.status === 'completed') {
              if (pollRef.current) {
                clearInterval(pollRef.current)
                pollRef.current = null
              }
              // 加载预览行
              const rowsResp = await systemApi.getBatchRows(batchId, 0, PREVIEW_LIMIT)
              const currentYamlHash = hashYamlText(useDslProjectStore.getState().yamlText)
              useGenericSimStore.getState().succeed({
                projectId,
                runId,
                epoch,
                columns: st.columns ?? [],
                previewRows: (rowsResp.rows ?? []) as Array<Record<string, unknown>>,
                completedCycles: st.cyclesCompleted ?? 0,
                currentYamlHash,
                displayColumns: st.displayColumns ?? [],
                plotScales: st.plotScales ?? {},
              })
              resolve()
            } else if (st.status === 'failed' || st.status === 'cancelled' || st.status === 'interrupted') {
              if (pollRef.current) {
                clearInterval(pollRef.current)
                pollRef.current = null
              }
              useGenericSimStore.getState().fail({
                projectId,
                runId,
                epoch,
                error: st.error || `任务${st.status}`,
              })
              resolve()
            }
          } catch (pollErr: any) {
            // 轮询失败不立即终止，下次重试
          }
        }, POLL_INTERVAL_MS)
      })
    } catch (err: any) {
      fail({ projectId, runId, epoch, error: err?.message || String(err) })
    } finally {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      await cleanupTempYAML(tempPath)
      useGenericSimStore.getState().endGlobalBatch(runId)
      refreshStatus()
    }
  }

  const openExport = () => {
    setExportError(null)
    const sim = useGenericSimStore.getState()
    const currentProjectId = useDslProjectStore.getState().projectId
    if (!sim.hasExportableResult(currentProjectId)) {
      setExportError(sim.stale ? '结果已过期，请重新仿真后再导出' : '当前没有可导出的仿真结果')
      return
    }
    const session = createExportSession({
      projectId: currentProjectId,
      boundRunId: sim.boundRunId,
      boundYamlHash: sim.boundYamlHash,
      batchId: sim.batchId,
      columns: sim.columns,
      selectedColumns: sim.selectedColumns,
      previewRows: sim.previewRows,
    })
    if (!session) return
    setExportSession(session)
    setExportOpen(true)
  }

  const handleExport = async (opts: { format: ExportFormat; columns: string[]; sheetName: string }) => {
    setExportError(null)
    const session = exportSession
    if (!session) {
      setExportError('导出会话已失效，请重新打开导出窗口')
      return
    }
    const check = () => {
      const sim = useGenericSimStore.getState()
      const currentProjectId = useDslProjectStore.getState().projectId
      return validateExportSession(session, {
        projectId: currentProjectId,
        boundRunId: sim.boundRunId,
        boundYamlHash: sim.boundYamlHash,
        stale: sim.stale,
        hasDisplayResult: sim.hasDisplayResult(currentProjectId),
      })
    }
    const invalidBefore = check()
    if (invalidBefore) {
      setExportError(invalidBefore)
      return
    }
    const metadataError = validateExportRowMetadata(session.previewRows)
    if (metadataError) {
      setExportError(metadataError)
      return
    }
    const exportColumns = sanitizeExportColumns(opts.columns)
    if (exportColumns.length === 0) {
      setExportError('请选择至少一个可导出的数据列')
      return
    }
    setExportBusy(true)
    try {
      const path = await systemApi.saveExportFile(opts.format)
      if (!path) return
      const invalidAfter = check()
      if (invalidAfter) {
        setExportError(invalidAfter)
        return
      }
      // 从 SQLite 流式导出，只传 batchId
      await systemApi.exportBatchResult(
        session.batchId,
        exportColumns,
        path,
        opts.format,
        opts.sheetName,
      )
      setExportOpen(false)
      setExportSession(null)
    } catch (err: any) {
      setExportError(err?.message || String(err))
    } finally {
      setExportBusy(false)
      refreshStatus()
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="generic-sim-panel">
      {/* 控制条 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
        <label className="flex items-center gap-1.5">
          <span className="text-muted-foreground">周期数</span>
          <input
            type="number"
            min={1}
            value={cycles}
            disabled={running}
            onChange={(e) => setCycles(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-card px-2 py-1"
            data-testid="sim-cycles"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-muted-foreground">控制周期(s)</span>
          <input
            type="number"
            min={0.001}
            step={0.1}
            value={cycleTime}
            disabled={running}
            onChange={(e) => setCycleTime(Number(e.target.value))}
            className="w-20 rounded-md border border-border bg-card px-2 py-1"
            data-testid="sim-cycle-time"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-muted-foreground">采样周期(s)</span>
          <input
            type="number"
            min={0}
            step={0.1}
            value={sampleInterval}
            disabled={running}
            onChange={(e) => setSampleInterval(Number(e.target.value))}
            className="w-20 rounded-md border border-border bg-card px-2 py-1"
            placeholder="=控制周期"
            data-testid="sim-sample-interval"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-muted-foreground">起始时间</span>
          <input
            type="datetime-local"
            value={startTime}
            disabled={running}
            onChange={(e) => setStartTime(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-1"
            data-testid="sim-start-time"
          />
        </label>
        <button
          type="button"
          onClick={() => void handleStart()}
          disabled={!canStart}
          className="rounded-md bg-green-600 px-3 py-1.5 font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-40 disabled:hover:bg-green-600"
          data-testid="sim-start-button"
        >
          {running ? '仿真中…' : '开始仿真'}
        </button>
        <span className="flex items-center gap-1.5" data-testid="sim-status">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              running
                ? 'animate-pulse bg-green-500'
                : status === 'success' && owned
                  ? stale
                    ? 'bg-amber-500'
                    : 'bg-emerald-500'
                  : status === 'failed' && owned
                    ? 'bg-red-500'
                    : 'bg-muted-foreground/40'
            }`}
            aria-hidden
          />
          <span className="text-muted-foreground">
            {statusLabel(status, owned)}
            {status === 'success' && owned ? ` · ${completedCycles} 周期` : ''}
            {stale && owned ? ' · 已过期' : ''}
            {dfRunning ? ' · 实时占用' : ''}
            {batchBusy && !running ? ' · 全局批量任务运行中' : ''}
          </span>
        </span>
        <div className="min-w-2 flex-1" />
        <button
          type="button"
          onClick={openExport}
          disabled={!hasExportable || exportBusy}
          className="rounded-md border border-border bg-card px-3 py-1.5 transition-colors hover:bg-secondary disabled:opacity-40 disabled:hover:bg-card"
          data-testid="sim-export-button"
        >
          导出…
        </button>
      </div>

      {/* 错误消息 */}
      {displayError ? (
        <div className="whitespace-pre-wrap break-all border-b border-border bg-red-50 px-3 py-1.5 text-xs text-destructive" data-testid="sim-error">
          {displayError}
        </div>
      ) : null}
      {stale && owned && hasDisplay ? (
        <div className="border-b border-border bg-amber-50 px-3 py-1.5 text-xs text-amber-900" data-testid="generic-sim-stale">
          结果已过期（YAML 已修改）。可查看，但不得作为当前工程结果导出；请重新仿真。
        </div>
      ) : null}

      {/* 列配置 */}
      {numericColumns.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2" data-testid="generic-sim-columns">
          <span className="text-[11px] text-muted-foreground">显示列</span>
          {numericColumns.map((col) => {
            const selIdx = selectedColumns.indexOf(col)
            const selected = selIdx >= 0
            const color = selected ? COLORS[selIdx % COLORS.length] : undefined
            return (
              <button
                key={col}
                type="button"
                onClick={() => toggleColumn(col)}
                className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] transition-colors ${
                  selected
                    ? 'border-primary/40 bg-primary/10 text-foreground'
                    : 'border-border text-muted-foreground hover:border-primary/30 hover:text-foreground'
                }`}
                data-testid={`sim-column-${col}`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full transition-colors"
                  style={{ backgroundColor: color ?? 'transparent', border: color ? 'none' : '1px solid currentColor' }}
                  aria-hidden
                />
                {col}
              </button>
            )
          })}
        </div>
      ) : null}

      {/* 图表区：flex-1 占满剩余高度 */}
      <div className="min-h-0 flex-1 p-2">
        {!owned || !hasDisplay ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground" data-testid="generic-sim-empty">
            <svg width="40" height="28" viewBox="0 0 40 28" fill="none" aria-hidden className="opacity-40">
              <path d="M2 24 L10 14 L18 18 L26 6 L38 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 26 H38" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span className="text-xs">{running ? '仿真运行中…' : '运行仿真后在此查看结果趋势'}</span>
          </div>
        ) : selectedColumns.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            请选择至少一个数值列
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="_cycle" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {selectedColumns.map((col, i) => (
                <Line
                  key={col}
                  type="monotone"
                  name={hasPlotScale(plotScales, col) ? `${col}（量程%）` : col}
                  dataKey={col}
                  stroke={COLORS[i % COLORS.length]}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* 统计行 */}
      {owned && hasDisplay ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-1.5 font-mono text-[11px] text-muted-foreground" data-testid="generic-sim-stats">
          <span>
            {completedCycles} 行 · {columns.length} 列（预览 {previewRows.length} 行）
          </span>
          {stats.map(({ col, stat }) => (
            <span key={col} title={col}>
              <span className="text-foreground/70">{col}</span>
              {'  min '}
              {fmt(stat.min)}
              {'  max '}
              {fmt(stat.max)}
              {'  终值 '}
              {fmt(stat.last)}
            </span>
          ))}
        </div>
      ) : null}

      <ExportDialog
        open={exportOpen}
        session={exportSession}
        busy={exportBusy}
        error={exportError}
        onClose={() => {
          setExportOpen(false)
          setExportSession(null)
        }}
        onExport={(opts) => void handleExport(opts)}
      />
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
