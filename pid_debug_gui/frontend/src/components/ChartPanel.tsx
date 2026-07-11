import { useMemo, useCallback } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useStore } from '../store/useStore'
import { cn } from '../lib/utils'

const COLORS = [
  '#3b82f6', '#ef4444', '#22c55e', '#f59e0b',
  '#8b5cf6', '#ec4899', '#06b6d4', '#f97316',
  '#14b8a6', '#6366f1',
]

export default function ChartPanel() {
  const { snapshotHistory, displayVars, selectedVars, setSelectedVars } =
    useStore()

  const allVarNames = useMemo(
    () => displayVars.map((v) => v.name),
    [displayVars]
  )

  const toggleVar = useCallback(
    (name: string) => {
      setSelectedVars(
        selectedVars.includes(name)
          ? selectedVars.filter((v) => v !== name)
          : [...selectedVars, name]
      )
    },
    [selectedVars, setSelectedVars]
  )

  const chartData = useMemo(() => {
    if (snapshotHistory.length === 0) return []
    return snapshotHistory
      .map((snap, i) => {
        const point: Record<string, number | string> = { _cycle: i }
        for (const name of selectedVars) {
          const val = snap[name]
          point[name] = typeof val === 'number' ? val : 0
        }
        return point
      })
  }, [snapshotHistory, selectedVars])

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Var selector */}
      <div className="flex items-center gap-1 px-3 py-1.5 bg-gray-800 border-b border-gray-700 overflow-x-auto">
        <span className="text-xs text-gray-500 mr-1 flex-shrink-0">位号:</span>
        {allVarNames.map((name, i) => (
          <button
            key={name}
            className={cn(
              'px-2 py-0.5 text-xs rounded whitespace-nowrap transition-colors',
              selectedVars.includes(name)
                ? 'text-white'
                : 'text-gray-500 hover:text-gray-300 bg-gray-700'
            )}
            style={
              selectedVars.includes(name)
                ? { backgroundColor: COLORS[i % COLORS.length] + '44', color: COLORS[i % COLORS.length] }
                : undefined
            }
            onClick={() => toggleVar(name)}
          >
            {name}
          </button>
        ))}
        {allVarNames.length === 0 && (
          <span className="text-xs text-gray-600">无 display 变量</span>
        )}
      </div>

      {/* Chart */}
      <div className="flex-1 p-3 min-h-0">
        {chartData.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="_cycle"
                stroke="#9ca3af"
                tick={{ fontSize: 11 }}
                label={{ value: 'cycle', position: 'insideBottomRight', style: { fill: '#9ca3af', fontSize: 11 } }}
              />
              <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '4px',
                  fontSize: '12px',
                  color: '#e5e7eb',
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: '11px', color: '#9ca3af' }}
              />
              {selectedVars.map((name, i) => (
                <Line
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stroke={COLORS[i % COLORS.length]}
                  dot={false}
                  isAnimationActive={false}
                  strokeWidth={1.5}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">
            {selectedVars.length === 0
              ? '请在上方选择要显示的位号'
              : '等待数据...'}
          </div>
        )}
      </div>
    </div>
  )
}
