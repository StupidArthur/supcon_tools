import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useRuntimeStore } from './useRuntimeStore'
import { downsample } from './trendBuffer'

const MAX_CURVES = 8
const MAX_POINTS = 2500
const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

interface Props {
  projectId?: string
}

function prefsKey(projectId?: string): string {
  return `realtimeTrendPrefs:${projectId ?? 'default'}`
}

export function GenericTrendPanel({ projectId }: Props) {
  const tagCatalog = useRuntimeStore((s) => s.tagCatalog)
  const trendBuffer = useRuntimeStore((s) => s.trendBuffer)
  const latestFrame = useRuntimeStore((s) => s.latestFrame)
  const previousRunSeries = useRuntimeStore((s) => s.previousRunSeries)
  const setTrendTags = useRuntimeStore((s) => s.setTrendTags)

  const [selected, setSelected] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [normalized, setNormalized] = useState(false)
  const [showPrevious, setShowPrevious] = useState(false)
  const [initialized, setInitialized] = useState(false)

  const numericTags = useMemo(
    () => tagCatalog.filter((t) => t.dataType === 'number'),
    [tagCatalog],
  )

  // 默认选中 display=true 的前 4 个数值 tag；无 display tag 时不擅自选择。
  useEffect(() => {
    if (initialized || numericTags.length === 0) return
    let initial: string[] = []
    const saved = localStorage.getItem(prefsKey(projectId))
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed?.selected)) initial = parsed.selected
      } catch {
        // ignore
      }
    }
    if (initial.length === 0) {
      initial = numericTags.filter((t) => t.display).slice(0, 4).map((t) => t.name)
    }
    setSelected(initial.slice(0, MAX_CURVES))
    setInitialized(true)
  }, [numericTags, initialized, projectId])

  useEffect(() => {
    setTrendTags(selected)
    try {
      localStorage.setItem(prefsKey(projectId), JSON.stringify({ selected }))
    } catch {
      // ignore
    }
  }, [selected, setTrendTags, projectId])

  const scaleRef = useMemo(() => {
    const m: Record<string, number | undefined> = {}
    for (const t of tagCatalog) m[t.name] = t.plotScaleRef
    return m
  }, [tagCatalog])

  const series = useMemo(() => trendBuffer.toArray(), [trendBuffer, latestFrame])

  const chartData = useMemo(() => {
    const down = downsample(series, MAX_POINTS)
    const t0 = down.length > 0 && down[0].simTime == null ? (down[0] as any).receivedAt : null
    return down.map((p) => {
      const x = p.simTime != null ? p.simTime : null
      const row: Record<string, number | null> = { x }
      for (const tag of selected) {
        let v = p.values[tag]
        if (v != null && normalized && scaleRef[tag]) {
          v = (v * 100) / (scaleRef[tag] as number)
        }
        row[tag] = v
      }
      return row
    })
  }, [series, selected, normalized, scaleRef])

  const toggleTag = (tag: string) => {
    setSelected((prev) => {
      if (prev.includes(tag)) return prev.filter((t) => t !== tag)
      if (prev.length >= MAX_CURVES) return prev
      return [...prev, tag]
    })
  }

  const filteredCatalog = search
    ? numericTags.filter((t) => t.name.toLowerCase().includes(search.toLowerCase()))
    : numericTags

  const currentValue = (tag: string): string => {
    const v = latestFrame?.values[tag]
    return typeof v === 'number' ? v.toFixed(4) : '—'
  }

  return (
    <section className="space-y-2" data-testid="generic-trend-panel">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium">趋势</span>
        <input
          type="text"
          placeholder="搜索位号..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-40 rounded border border-border bg-background px-2 py-0.5 text-xs"
          data-testid="trend-search"
        />
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={normalized}
            onChange={(e) => setNormalized(e.target.checked)}
          />
          百分比归一化
        </label>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={showPrevious}
            onChange={(e) => setShowPrevious(e.target.checked)}
          />
          上一轮
        </label>
        <button
          type="button"
          onClick={() => trendBuffer.clear()}
          className="rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary"
          data-testid="trend-clear"
        >
          清空
        </button>
        <span className="text-xs text-muted-foreground">({selected.length}/{MAX_CURVES})</span>
      </div>

      <div className="flex flex-wrap gap-1">
        {filteredCatalog.slice(0, 50).map((t) => (
          <button
            key={t.name}
            type="button"
            onClick={() => toggleTag(t.name)}
            className={`rounded border px-1.5 py-0.5 text-xs ${
              selected.includes(t.name)
                ? 'border-primary bg-primary/10'
                : 'border-border hover:bg-secondary'
            }`}
          >
            {t.name}
          </button>
        ))}
      </div>

      {selected.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
          选择位号以显示趋势。
        </div>
      ) : (
        <div className="h-72 w-full" data-testid="trend-chart">
          <LineChart width={720} height={280} data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="x" type="number" domain={['auto', 'auto']} fontSize={10} />
            <YAxis fontSize={10} />
            <Tooltip />
            <Legend />
            {selected.map((tag, i) => (
              <Line
                key={tag}
                type="monotone"
                dataKey={tag}
                stroke={COLORS[i % COLORS.length]}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-xs">
        {selected.map((tag, i) => (
          <span key={tag} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            <span className="font-mono">{tag}</span>
            <span className="text-muted-foreground">{currentValue(tag)}{normalized ? '%' : ''}</span>
          </span>
        ))}
      </div>
      {showPrevious && previousRunSeries.length > 0 ? (
        <div className="text-xs text-muted-foreground">上一轮运行：{previousRunSeries.length} 点</div>
      ) : null}
    </section>
  )
}
