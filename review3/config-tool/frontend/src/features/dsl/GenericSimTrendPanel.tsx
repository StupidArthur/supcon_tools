/**
 * Generic offline simulation trend — numeric columns only, no PID/tank assumptions.
 * Only shows results owned by the current projectId.
 */
import { useMemo } from 'react'
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
import { useDslProjectStore } from './useDslProjectStore'
import { useGenericSimStore } from './useGenericSimStore'

const COLORS = ['#3b82f6', '#06b6d4', '#f97316', '#10b981', '#8b5cf6', '#ec4899', '#f59e0b', '#6366f1']

function isNumericColumn(rows: Array<Record<string, unknown>>, col: string): boolean {
  for (const row of rows.slice(0, 50)) {
    const v = row[col]
    if (typeof v === 'number' && Number.isFinite(v)) return true
  }
  return false
}

export function GenericSimTrendPanel() {
  const projectId = useDslProjectStore((s) => s.projectId)
  const status = useGenericSimStore((s) => s.status)
  const columns = useGenericSimStore((s) => s.columns)
  const rows = useGenericSimStore((s) => s.rows)
  const selectedColumns = useGenericSimStore((s) => s.selectedColumns)
  const stale = useGenericSimStore((s) => s.stale)
  const boundProjectId = useGenericSimStore((s) => s.boundProjectId)
  const toggleColumn = useGenericSimStore((s) => s.toggleColumn)
  const hasDisplay = useGenericSimStore((s) => s.hasDisplayResult(projectId))

  const owned = boundProjectId === projectId && hasDisplay

  const numericColumns = useMemo(
    () => (owned ? columns.filter((c) => c !== '_cycle' && isNumericColumn(rows, c)) : []),
    [columns, rows, owned],
  )

  const chartData = useMemo(() => {
    if (!owned) return []
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
  }, [rows, selectedColumns, owned])

  if (!owned) {
    return (
      <div className="p-4 text-xs text-muted-foreground" data-testid="generic-sim-trend-empty">
        请先运行仿真
      </div>
    )
  }

  return (
    <div className="space-y-3 p-3 text-xs" data-testid="generic-sim-trend">
      <div className="font-medium">结果趋势</div>
      {stale ? (
        <div className="rounded-md bg-amber-50 px-2 py-1 text-amber-900" data-testid="generic-sim-stale">
          结果已过期（YAML 已修改）。可查看，但不得作为当前工程结果导出；请重新仿真。
        </div>
      ) : null}
      <div data-testid="generic-sim-meta">
        结果行数：{rows.length} · 字段：{columns.join(', ') || '（无）'} · 状态：{status}
      </div>

      <div className="flex flex-wrap gap-2">
        {numericColumns.map((col) => (
          <label
            key={col}
            className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-0.5 ${
              selectedColumns.includes(col)
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground'
            }`}
          >
            <input
              type="checkbox"
              checked={selectedColumns.includes(col)}
              onChange={() => toggleColumn(col)}
            />
            {col}
          </label>
        ))}
        {numericColumns.length === 0 ? (
          <span className="text-muted-foreground">无数值列可绘制</span>
        ) : null}
      </div>

      {selectedColumns.length > 0 ? (
        <div className="h-64 w-full" data-testid="generic-sim-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="_cycle" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
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
        </div>
      ) : (
        <div className="text-muted-foreground">请选择至少一个数值列</div>
      )}
    </div>
  )
}
