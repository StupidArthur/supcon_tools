import { useCallback, useEffect, useState } from 'react'
import { realtimeRuntimeApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'

interface AlarmStatus {
  id: string
  name: string
  tag: string
  severity: string
  direction: string
  state: string
  value: number | null
  limit: number
  activatedAt: string | null
  acknowledgedAt: string | null
  message: string
}

interface AlarmEvent {
  id: string
  name: string
  tag: string
  severity: string
  type: string
  value: number | null
  time: string
}

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, warning: 2, info: 3 }
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'bg-red-100 text-red-900',
  high: 'bg-orange-100 text-orange-900',
  warning: 'bg-amber-100 text-amber-900',
  info: 'bg-blue-100 text-blue-900',
}

const STATE_LABEL: Record<string, string> = {
  normal: '正常',
  pending: ' pending',
  active_unacked: '激活·未确认',
  active_acked: '激活·已确认',
  returned_unacked: '恢复·未确认',
}

export function AlarmPanel() {
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const session = useRealtimeRunSessionStore((s) => s.session)
  const [alarms, setAlarms] = useState<AlarmStatus[]>([])
  const [events, setEvents] = useState<AlarmEvent[]>([])
  const [severityFilter, setSeverityFilter] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const a = await realtimeRuntimeApi.getAlarms() as any
      setAlarms(a?.alarms || [])
      const e = await realtimeRuntimeApi.getAlarmEvents(100) as any
      setEvents(e?.events || [])
    } catch (err: any) {
      setError(String(err))
    }
  }, [])

  useEffect(() => {
    if (connectionState !== 'connected') return
    void refresh()
    const id = setInterval(() => void refresh(), 2000)
    return () => clearInterval(id)
  }, [connectionState, refresh])

  const handleAck = async (id: string) => {
    setError(null)
    try {
      await realtimeRuntimeApi.ackAlarm(id)
      await refresh()
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleAckAll = async () => {
    setError(null)
    try {
      await realtimeRuntimeApi.ackAllAlarms()
      await refresh()
    } catch (e: any) {
      setError(String(e))
    }
  }

  const activeAlarms = alarms
    .filter((a) => a.state !== 'normal')
    .filter((a) => !severityFilter || a.severity === severityFilter)
    .filter((a) => !search || a.name.toLowerCase().includes(search.toLowerCase()) || a.tag.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9))

  const unackedCount = alarms.filter((a) => a.state === 'active_unacked' || a.state === 'returned_unacked').length

  if (!session) {
    return null
  }

  return (
    <section className="space-y-2" data-testid="alarm-panel">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium">报警</span>
        {unackedCount > 0 ? (
          <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-900" data-testid="alarm-unacked-count">
            未确认 {unackedCount}
          </span>
        ) : null}
        {connectionState === 'disconnected' ? (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">连接断开</span>
        ) : null}
        <input
          type="text"
          placeholder="搜索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-32 rounded border border-border bg-background px-2 py-0.5 text-xs"
        />
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="rounded border border-border bg-background px-2 py-0.5 text-xs"
        >
          <option value="">全部级别</option>
          <option value="critical">critical</option>
          <option value="high">high</option>
          <option value="warning">warning</option>
          <option value="info">info</option>
        </select>
        <button
          type="button"
          onClick={() => void handleAckAll()}
          className="rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary"
          data-testid="alarm-ack-all"
        >
          全部确认
        </button>
      </div>

      {activeAlarms.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          无活跃报警
        </div>
      ) : (
        <div className="space-y-1">
          {activeAlarms.map((a) => (
            <div key={a.id} className="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-xs">
              <span className={`rounded px-1.5 py-0.5 ${SEVERITY_COLOR[a.severity] || ''}`}>{a.severity}</span>
              <span className="font-medium">{a.name}</span>
              <span className="font-mono text-muted-foreground">{a.tag}</span>
              <span className="text-muted-foreground">
                {a.value != null ? a.value.toFixed(3) : '—'} / {a.limit} ({a.direction === 'high' ? '高' : '低'})
              </span>
              <span className="text-muted-foreground">{STATE_LABEL[a.state] || a.state}</span>
              {(a.state === 'active_unacked' || a.state === 'returned_unacked') ? (
                <button
                  type="button"
                  onClick={() => void handleAck(a.id)}
                  className="ml-auto rounded border border-border px-2 py-0.5 hover:bg-secondary"
                >
                  确认
                </button>
              ) : (
                <span className="ml-auto text-muted-foreground">{a.message}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {events.length > 0 ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">最近事件 ({events.length})</summary>
          <div className="mt-1 max-h-40 overflow-y-auto rounded-md border border-border p-2">
            {[...events].reverse().map((e, i) => (
              <div key={i} className="flex gap-2 py-0.5">
                <span className="text-muted-foreground">{e.time}</span>
                <span className={`rounded px-1 ${SEVERITY_COLOR[e.severity] || ''}`}>{e.severity}</span>
                <span>{e.name}</span>
                <span className="text-muted-foreground">{e.type}</span>
                <span className="font-mono">{e.value != null ? e.value : '—'}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
          {error}
        </div>
      ) : null}
    </section>
  )
}
