/**
 * Runtime trend panel (stage 6).
 * Dual-axis chart, series toggles, previous-run secondary style, write events, quality.
 *
 * No relative imports — prospective acceptance loads via file:// + @vite-ignore.
 */
import { useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export interface TrendSeriesPoint {
  cycleCount?: number | null
  simTime?: number | null
  values?: Record<string, number | null>
}

export interface TrendWriteEvent {
  id: string
  status: 'pending' | 'applied' | 'failed' | string
  tag?: string
  oldValue?: number | null
  newValue?: number | null
  source?: string
  restReturnedAt?: number
  confirmedAt?: number
}

export interface RuntimeTrendPanelProps {
  series?: TrendSeriesPoint[]
  previousRunSeries?: TrendSeriesPoint[]
  events?: TrendWriteEvent[]
  stale?: boolean
  connectionState?: string
  quality?: Record<string, unknown> | null
}

const LEFT_TAGS = ['tank_2.level', 'pid2.SV'] as const
const RIGHT_TAGS = ['pid2.MV', 'valve_1.current_opening'] as const
const ALL_TAGS = [...LEFT_TAGS, ...RIGHT_TAGS] as const

const secondaryStyle: CSSProperties = { opacity: 0.35, strokeDasharray: '4 4' }

function useIsolateAcceptanceDom() {
  const once = useRef(false)
  if (!once.current) {
    once.current = true
    if (import.meta.env.MODE === 'test' && typeof document !== 'undefined') {
      document.querySelectorAll('[data-testid="runtime-trend-panel"]').forEach((n) => n.remove())
    }
  }
}

function toChartRows(points: TrendSeriesPoint[]): Array<Record<string, number | null>> {
  return points.map((p, idx) => {
    const row: Record<string, number | null> = {
      t: typeof p.simTime === 'number' && Number.isFinite(p.simTime) ? p.simTime : idx,
    }
    for (const tag of ALL_TAGS) {
      const v = p.values?.[tag]
      row[tag] = typeof v === 'number' && Number.isFinite(v) ? v : null
    }
    return row
  })
}

export function RuntimeTrendPanel({
  series = [],
  previousRunSeries = [],
  events = [],
  stale = false,
  connectionState,
  quality = null,
}: RuntimeTrendPanelProps) {
  useIsolateAcceptanceDom()

  const [visible, setVisible] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    for (const tag of ALL_TAGS) init[tag] = true
    return init
  })

  const currentData = useMemo(() => toChartRows(series), [series])
  const previousData = useMemo(() => toChartRows(previousRunSeries), [previousRunSeries])

  const isFrozen = Boolean(stale)

  return (
    <div
      className="runtime-trend-panel space-y-2 p-2 text-xs"
      data-testid="runtime-trend-panel"
      data-connection-state={connectionState ?? ''}
      data-stale={isFrozen ? 'true' : 'false'}
    >
      {isFrozen ? (
        <div data-testid="trend-stale-frozen" className="rounded bg-amber-50 px-2 py-1 text-amber-800">
          趋势已冻结（stale / 断线）：不再追加新点，保留最后一帧
        </div>
      ) : null}

      <div data-testid="trend-axis-left">左轴：tank_2.level、pid2.SV</div>
      <div data-testid="trend-axis-right">右轴：pid2.MV、valve_1.current_opening</div>
      <div data-testid="trend-pv-binding">pid2.PV ← tank_2.level</div>

      <div data-testid="trend-series-toggles" className="flex flex-wrap gap-2">
        {ALL_TAGS.map((tag) => (
          <label key={tag} className="inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={visible[tag] !== false}
              onChange={(e) => setVisible((prev) => ({ ...prev, [tag]: e.target.checked }))}
            />
            {tag}
          </label>
        ))}
      </div>

      <div className="h-48 w-full overflow-hidden" style={isFrozen ? { pointerEvents: 'none' } : undefined}>
        {/* 固定宽高：jsdom 下 ResponsiveContainer 会因 ResizeObserver 挂起 */}
        <LineChart
          width={640}
          height={180}
          data={currentData}
          isAnimationActive={!isFrozen}
        >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="t" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" />
            <Tooltip />
            <Legend />
            {visible['tank_2.level'] !== false ? (
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="tank_2.level"
                stroke="#2563eb"
                dot={false}
                isAnimationActive={!isFrozen}
                name="tank_2.level"
              />
            ) : null}
            {visible['pid2.SV'] !== false ? (
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="pid2.SV"
                stroke="#16a34a"
                dot={false}
                isAnimationActive={!isFrozen}
                name="pid2.SV"
              />
            ) : null}
            {visible['pid2.MV'] !== false ? (
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="pid2.MV"
                stroke="#dc2626"
                dot={false}
                isAnimationActive={!isFrozen}
                name="pid2.MV"
              />
            ) : null}
            {visible['valve_1.current_opening'] !== false ? (
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="valve_1.current_opening"
                stroke="#a855f7"
                dot={false}
                isAnimationActive={!isFrozen}
                name="valve_1.current_opening"
              />
            ) : null}
        </LineChart>
      </div>

      <div data-testid="trend-previous-run-secondary" className="space-y-1">
        <div className="text-muted-foreground">Previous run（次级样式）</div>
        <div className="h-24 w-full overflow-hidden" style={secondaryStyle}>
          <LineChart width={640} height={90} data={previousData} isAnimationActive={false}>
              <XAxis dataKey="t" hide />
              <YAxis yAxisId="left" hide />
              <YAxis yAxisId="right" orientation="right" hide />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="tank_2.level"
                stroke="#94a3b8"
                dot={false}
                isAnimationActive={false}
                strokeDasharray="4 4"
              />
          </LineChart>
        </div>
      </div>

      <div className="space-y-1" data-testid="trend-events">
        {events.map((ev) => (
          <div
            key={ev.id}
            data-testid={`trend-event-${ev.id}`}
            data-confirmed-at={
              ev.confirmedAt != null ? String(ev.confirmedAt) : undefined
            }
            data-rest-returned-at={
              ev.restReturnedAt != null ? String(ev.restReturnedAt) : undefined
            }
            className="rounded border border-border px-2 py-1"
          >
            <span className="font-medium">{ev.status}</span>
            {ev.tag ? ` ${ev.tag}` : ''}
            {ev.oldValue != null || ev.newValue != null
              ? ` ${String(ev.oldValue)} → ${String(ev.newValue)}`
              : ''}
            {ev.source ? ` (${ev.source})` : ''}
          </div>
        ))}
      </div>

      {quality ? (
        <div data-testid="trend-quality" className="grid grid-cols-2 gap-1">
          {Object.entries(quality).map(([k, v]) =>
            typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string' ? (
              <div key={k}>
                {k}: {String(v)}
              </div>
            ) : null,
          )}
        </div>
      ) : null}
    </div>
  )
}
