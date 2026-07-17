import { useState, useMemo, useEffect } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { useStore } from '../store/useStore'

const COLORS = ['#3b82f6', '#06b6d4', '#f97316', '#10b981', '#8b5cf6', '#ec4899', '#f59e0b', '#6366f1']

// 默认选中的位号关键词
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

export function ChartPanel() {
  const batchResult = useStore((s) => s.batchResult)
  const batchRunning = useStore((s) => s.batchRunning)

  const [selectedCols, setSelectedCols] = useState<string[]>([])
  const [autoY, setAutoY] = useState(true)

  // 数据列（排除 _cycle 元数据）
  const plotColumns = useMemo(() => {
    if (!batchResult) return []
    return batchResult.columns.filter((c) => c !== '_cycle')
  }, [batchResult])

  // 初始化默认选中列
  useEffect(() => {
    if (plotColumns.length > 0 && selectedCols.length === 0) {
      setSelectedCols(defaultSelected(plotColumns))
    }
  }, [plotColumns, selectedCols.length])

  const toggleCol = (col: string) => {
    setSelectedCols((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    )
  }

  if (!batchResult || batchResult.rows.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">
          {batchRunning ? '仿真运行中...' : '选择配置并运行仿真以查看曲线'}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-background">
      {/* 位号选择 */}
      <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b border-border">
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
        <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={autoY}
            onChange={(e) => setAutoY(e.target.checked)}
          />
          Y轴自动量程
        </label>
      </div>

      {/* 图表 */}
      <div className="flex-1 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={batchResult.rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="_cycle"
              tick={{ fontSize: 10 }}
              label={{ value: '周期', position: 'insideBottom', offset: -5, style: { fontSize: 11 } }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 10 }}
              domain={autoY ? ['auto', 'auto'] : [0, 100]}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 10 }}
              domain={autoY ? ['auto', 'auto'] : [0, 100]}
            />
            <Tooltip
              contentStyle={{
                fontSize: 11,
                borderRadius: 6,
                border: '1px solid hsl(var(--border))',
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {selectedCols.map((col, i) => {
              // 简单分组：MV 类放右轴，其他放左轴
              const isRightAxis = col.toLowerCase().includes('mv') || col.toLowerCase().includes('opening')
              return (
                <Line
                  key={col}
                  type="monotone"
                  dataKey={col}
                  yAxisId={isRightAxis ? 'right' : 'left'}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              )
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* 数据摘要 */}
      <div className="px-3 py-1 border-t border-border text-xs text-muted-foreground">
        {batchResult.rows.length} 行 × {plotColumns.length} 列
      </div>
    </div>
  )
}
