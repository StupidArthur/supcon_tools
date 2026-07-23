/**
 * 通用离线仿真一体面板 —— 运行控制 + 列配置 + 趋势大图 + 导出 + 统计。
 *
 * 供 generic YAML 工程的右栏使用：图表占满剩余高度（flex-1），
 * 不再是固定 256px 的小图。合并了原 仿真运行 / 结果趋势 / 导出 三个 Tab。
 *
 * 业务规则与原 SimControlPanel / GenericSimTrendPanel / SimExportPanel 完全一致：
 * - 点击运行时冻结 YAML 快照，运行中编辑不影响本次结果
 * - 完成后与当前草稿 hash 比较，不一致标记 stale 并禁止导出
 * - 结果按 projectId / runId / epoch 归属，迟到结果丢弃
 */
import { useEffect, useMemo, useState } from 'react'
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
import { backendBatchBusy, useCanvasStore } from '../../store/useCanvasStore'
import { ExportDialog, type ExportFormat } from './ExportDialog'
import { cleanupTempYAML, materializeYamlTextToTemp } from './materializeYamlDraft'
import { useDslProjectStore } from './useDslProjectStore'
import {
  DEFAULT_OFFLINE_SIM_CYCLES,
  hashYamlText,
  useGenericSimStore,
} from './useGenericSimStore'

const COLORS = ['#3b82f6', '#06b6d4', '#f97316', '#10b981', '#8b5cf6', '#ec4899', '#f59e0b', '#6366f1']

function isNumericColumn(rows: Array<Record<string, unknown>>, col: string): boolean {
  for (const row of rows.slice(0, 50)) {
    const v = row[col]
    if (typeof v === 'number' && Number.isFinite(v)) return true
  }
  return false
}

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
  const rows = useGenericSimStore((s) => s.rows)
  const selectedColumns = useGenericSimStore((s) => s.selectedColumns)
  const stale = useGenericSimStore((s) => s.stale)
  const boundProjectId = useGenericSimStore((s) => s.boundProjectId)
  const setCycles = useGenericSimStore((s) => s.setCycles)
  const beginRun = useGenericSimStore((s) => s.beginRun)
  const succeed = useGenericSimStore((s) => s.succeed)
  const fail = useGenericSimStore((s) => s.fail)
  const toggleColumn = useGenericSimStore((s) => s.toggleColumn)
  const hasDisplay = useGenericSimStore((s) => s.hasDisplayResult(projectId))
  const exportable = useGenericSimStore((s) => s.hasExportableResult(projectId))
  const globalBatchRunning = useGenericSimStore((s) => s.globalBatchRunning)

  const [preflightError, setPreflightError] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const owned = boundProjectId === projectId
  const running = status === 'running' && owned
  const yamlText = useDslProjectStore((s) => s.yamlText)
  // Batch 占用 = 本地 lease（即时反馈） || 后端权威状态（跨刷新/跨页面）。
  const batchBusy = globalBatchRunning || backendBatchBusy(dfStatus)
  const canStart = !running && !dfRunning && !batchBusy && Boolean(yamlText.trim())
  const displayError = preflightError || (owned ? error : null)

  // 进入页面刷新一次后端状态；仅在 Batch 占用期间短周期轮询，结束后停止。
  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])
  useEffect(() => {
    if (!batchBusy) return
    const id = setInterval(() => refreshStatus(), 1000)
    return () => clearInterval(id)
  }, [batchBusy, refreshStatus])

  const numericColumns = useMemo(
    () =>
      owned && hasDisplay
        ? columns.filter((c) => c !== '_cycle' && !c.startsWith('_') && isNumericColumn(rows, c))
        : [],
    [columns, rows, owned, hasDisplay],
  )

  const chartData = useMemo(() => {
    if (!owned || !hasDisplay) return []
    return rows.map((row, idx) => {
      const point: Record<string, number | string> = {
        _cycle: typeof row._cycle === 'number' ? row._cycle : idx,
      }
      for (const col of selectedColumns) {
        const v = row[col]
        if (typeof v === 'number' && Number.isFinite(v)) {
          point[col] = v
        }
      }
      return point
    })
  }, [rows, selectedColumns, owned, hasDisplay])

  const stats = useMemo(() => {
    if (!owned || !hasDisplay) return [] as Array<{ col: string; stat: ColumnStat }>
    return selectedColumns
      .map((col) => ({ col, stat: columnStats(rows, col) }))
      .filter((x): x is { col: string; stat: ColumnStat } => x.stat !== null)
  }, [rows, selectedColumns, owned, hasDisplay])

  const handleStart = async () => {
    setPreflightError(null)
    setExportError(null)
    // 点击时再次读取最新状态，避免只依赖渲染时的旧值。
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
    // 全局批量占用 lease：真正结束后才在 finally 释放（按 runId 匹配）。
    useGenericSimStore.getState().beginGlobalBatch(runId)

    // 临时路径只属于本次异步任务（局部变量），在 finally 中自行清理；
    // 不写任何全局 Store，旧任务不会清理或覆盖其他任务的路径与 lease。
    let tempPath: string | null = null
    try {
      const exe = await systemApi.getDataFactoryPath()
      if (exe) {
        useCanvasStore.getState().setDfPath(exe)
      }
      tempPath = await materializeYamlTextToTemp(yamlSnapshot)
      const result = await systemApi.runBatch(tempPath, n)
      const resultColumns = (result as any).columns || []
      const resultRows = ((result as any).rows || []) as Array<Record<string, unknown>>
      const displayColumns = ((result as any).displayColumns || []) as string[]
      const currentYamlHash = hashYamlText(useDslProjectStore.getState().yamlText)
      succeed({
        projectId,
        runId,
        epoch,
        columns: resultColumns,
        rows: resultRows,
        completedCycles: resultRows.length,
        currentYamlHash,
        displayColumns,
      })
    } catch (err: any) {
      fail({ projectId, runId, epoch, error: err?.message || String(err) })
    } finally {
      await cleanupTempYAML(tempPath)
      useGenericSimStore.getState().endGlobalBatch(runId)
      refreshStatus()
    }
  }

  const handleExport = async (opts: { format: ExportFormat; columns: string[]; sheetName: string }) => {
    setExportError(null)
    if (!exportable) {
      setExportError(stale && hasDisplay ? '结果已过期，禁止导出为当前工程结果' : '未运行成功，禁止导出')
      return
    }
    setExportBusy(true)
    try {
      const path = await systemApi.saveExportFile(opts.format)
      if (!path) return
      // 对话框返回后复查身份与 stale：工程/run 改变或已过期则取消。
      const cur = useGenericSimStore.getState()
      if (!cur.hasExportableResult(projectId)) {
        setExportError('工程已切换、结果已失效或已过期，取消导出')
        return
      }
      // 导出内容与趋势图完全一致：固定序号列 _cycle + 用户勾选列，全部来自当前内存 rows。
      // 不重新仿真、不重新物化 YAML。
      const exportColumns = ['_cycle', ...opts.columns]
      await systemApi.exportRowsFormatted(
        exportColumns,
        cur.rows as Array<Record<string, any>>,
        path,
        opts.format,
        opts.sheetName,
      )
      setExportOpen(false)
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
          onClick={() => {
            setExportError(null)
            setExportOpen(true)
          }}
          disabled={!hasDisplay}
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
            {rows.length} 行 · {columns.length} 列
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
        columns={numericColumns}
        defaultSelected={selectedColumns}
        rowCount={rows.length}
        busy={exportBusy}
        error={exportError}
        onClose={() => setExportOpen(false)}
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
