import { useEffect, useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtDateTime, FilterInput, applyFilters } from '@/lib/utils'
import { api, type ActorSnapshot, type ActorEvent, type HistoryRange } from '@/lib/api'

export function ActorsView({ clusterID, actors }: { clusterID: string; actors: ActorSnapshot[] }) {
  const [events, setEvents] = useState<ActorEvent[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const setFilter = (k: string, v: string) => setFilters((p) => ({ ...p, [k]: v }))

  // 加载近 24 小时的 Actor 事件流（仅 clusterID 变时重拉，避免每 5s 重拉）
  useEffect(() => {
    const to = Date.now()
    const from = to - 24 * 3600 * 1000
    const range: HistoryRange = { from, to }
    api.getActorEvents(clusterID, range).then(setEvents).catch(() => setEvents([]))
  }, [clusterID])

  const stateVariant = (s: string) =>
    s === 'ALIVE' ? 'success' : s === 'DEAD' ? 'destructive' : 'warning'

  const COLS = [
    { key: 'class', header: '类', getValue: (a: ActorSnapshot) => a.actorClass, right: false },
    { key: 'name', header: '名称', getValue: (a: ActorSnapshot) => a.name || '-', right: false },
    { key: 'state', header: '状态', getValue: (a: ActorSnapshot) => a.state, right: false },
    { key: 'restarts', header: '重启', getValue: (a: ActorSnapshot) => String(a.numRestarts), right: true },
    { key: 'exec', header: '已执行', getValue: (a: ActorSnapshot) => String(a.numExecTasks), right: true },
    { key: 'gpu', header: 'GPU', getValue: (a: ActorSnapshot) => (a.gpuUsed > 0 ? String(a.gpuUsed) : '-'), right: true },
    { key: 'exit', header: '死因', getValue: (a: ActorSnapshot) => (a.exitDetail && a.exitDetail !== '-' ? a.exitDetail : '-'), right: false },
  ]
  const colGetters = Object.fromEntries(COLS.map((c) => [c.key, c.getValue]))
  const filtered = useMemo(() => applyFilters(actors, filters, colGetters), [actors, filters])

  return (
    <div className="grid grid-cols-[1fr_360px] gap-3.5">
      {/* Actor 列表 */}
      <Card>
        <CardHeader>
          <CardTitle>Actor · 共 {filtered.length} / {actors.length} 个</CardTitle>
        </CardHeader>
        <CardContent>
          {actors.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">无 Actor</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  {COLS.map((c) => (
                    <TableHead key={c.key} className={c.right ? 'text-right' : ''}>
                      {c.header}
                    </TableHead>
                  ))}
                </TableRow>
                <TableRow>
                  {COLS.map((c) => (
                    <TableHead key={c.key} className={c.right ? 'text-right' : ''}>
                      <FilterInput value={filters[c.key] || ''} onChange={(v) => setFilter(c.key, v)} />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((a) => (
                  <TableRow key={a.actorId}>
                    <TableCell className="font-medium">{a.actorClass}</TableCell>
                    <TableCell className="max-w-[160px] truncate text-xs text-muted-foreground">{a.name || '-'}</TableCell>
                    <TableCell><Badge variant={stateVariant(a.state)}>{a.state}</Badge></TableCell>
                    <TableCell className="text-right">{a.numRestarts}</TableCell>
                    <TableCell className="text-right">{a.numExecTasks}</TableCell>
                    <TableCell className="text-right">{a.gpuUsed > 0 ? a.gpuUsed : '-'}</TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">{a.exitDetail && a.exitDetail !== '-' ? a.exitDetail : '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 事件流 */}
      <Card>
        <CardHeader>
          <CardTitle>状态变迁 · 近 24h</CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">无变迁事件</div>
          ) : (
            <div className="space-y-2">
              {events.map((e, i) => (
                <div key={i} className="rounded-md border border-border p-2.5 text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant={stateVariant(e.newState)}>{e.prevState} → {e.newState}</Badge>
                    <span className="text-muted-foreground">{fmtDateTime(e.ts)}</span>
                  </div>
                  <div className="mt-1 truncate text-muted-foreground">
                    {e.actorClass} · {e.deathCause && e.deathCause !== '-' ? e.deathCause : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
