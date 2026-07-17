import { useState, useEffect, useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { useCanvasStore } from '../store/useCanvasStore'
import { systemApi } from '../lib/api'

const COLORS = ['#3b82f6', '#06b6d4', '#f97316', '#10b981', '#8b5cf6', '#ec4899', '#f59e0b', '#6366f1']

function defaultSelected(columns: string[]): string[] {
  const picks: string[] = []
  for (const c of columns) {
    const lower = c.toLowerCase()
    if (lower.includes('sv') || lower.includes('level') || lower.includes('mv') || lower.includes('pv')) {
      picks.push(c)
    }
  }
  return picks.length > 0 ? picks : columns.slice(0, 3)
}

export function SimulationPanel() {
  const dfPath = useCanvasStore((s) => s.dfPath)
  const configs = useCanvasStore((s) => s.configs)
  const refreshConfigs = useCanvasStore((s) => s.refreshConfigs)

  const [selectedConfig, setSelectedConfig] = useState('')
  const [cycles, setCycles] = useState(100)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<{ columns: string[]; rows: any[] } | null>(null)
  const [selectedCols, setSelectedCols] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    systemApi.getDataFactoryPath().then(() => refreshConfigs())
  }, [])

  useEffect(() => {
    if (configs.length > 0 && !selectedConfig) {
      setSelectedConfig(configs[0])
    }
  }, [configs])

  const handleRun = async () => {
    setError('')
    setRunning(true)
    try {
      const res = await systemApi.runBatch(selectedConfig, cycles)
      const cols = (res as any).columns || []
      const rows = (res as any).rows || []
      setResult({ columns: cols, rows })
      setSelectedCols(defaultSelected(cols.filter((c: string) => c !== '_cycle')))
    } catch (e: any) {
      setError(String(e))
    } finally {
      setRunning(false)
    }
  }

  const handleExport = async () => {
    setError('')
    try {
      const path = await systemApi.saveYAMLFile()
      if (!path) return
      await systemApi.exportBatch(selectedConfig, cycles, path)
      alert('导出成功: ' + path)
    } catch (e: any) {
      alert('导出失败: ' + String(e))
    }
  }

  const toggleCol = (col: string) => {
    setSelectedCols((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    )
  }

  const plotColumns = useMemo(() => {
    if (!result) return []
    return result.columns.filter((c) => c !== '_cycle')
  }, [result])

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <h2 className="text-lg font-medium">仿真运行</h2>

        {/* Controls */}
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">配置文件</label>
            <select
              value={selectedConfig}
              onChange={(e) => setSelectedConfig(e.target.value)}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            >
              {configs.length === 0 && <option value="">（无可用配置）</option>}
              {configs.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">周期数</label>
            <input
              type="number"
              value={cycles}
              min={1}
              onChange={(e) => setCycles(Number(e.target.value))}
              className="w-28 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={running || !selectedConfig}
            className="rounded-md bg-primary px-4 py-1.5 text-xs text-primary-foreground hover:opacity-80 disabled:opacity-40"
          >
            {running ? '运行中...' : '运行仿真'}
          </button>
          {result && (
            <button
              onClick={handleExport}
              className="rounded-md border border-border bg-card px-4 py-1.5 text-xs hover:bg-secondary"
            >
              导出CSV
            </button>
          )}
        </div>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* Column selector */}
        {result && plotColumns.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {plotColumns.map((col) => (
              <label
                key={col}
                className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-0.5 text-xs ${
                  selectedCols.includes(col)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedCols.includes(col)}
                  onChange={() => toggleCol(col)}
                  className="hidden"
                />
                {col}
              </label>
            ))}
          </div>
        )}

        {/* Chart */}
        {result && result.rows.length > 0 && (
          <div className="rounded-md border border-border bg-card p-4">
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={result.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="_cycle"
                  tick={{ fontSize: 10 }}
                  label={{ value: '周期', position: 'insideBottom', offset: -5, style: { fontSize: 11 } }}
                />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip
                  contentStyle={{
                    fontSize: 11,
                    borderRadius: 6,
                    border: '1px solid hsl(var(--border))',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {selectedCols.map((col, i) => (
                  <Line
                    key={col}
                    type="monotone"
                    dataKey={col}
                    stroke={COLORS[i % COLORS.length]}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Data summary */}
        {result && (
          <div className="text-xs text-muted-foreground">
            {result.rows.length} 行 × {result.columns.length - 1} 列
          </div>
        )}
      </div>
    </div>
  )
}
