import { useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtBytes, FilterInput, applyFilters } from '@/lib/utils'
import { ExportSnapshotButton } from '@/components/ExportSnapshotButton'
import type { WorkerSnapshot, NodeMetric } from '@/lib/api'
import type { CollectionHealth } from '@/components/CollectionHealthNotice'

export function WorkersView({
  workers,
  nodes,
  sortBy,
  health,
  clusterName,
}: {
  workers: WorkerSnapshot[]
  nodes: NodeMetric[]
  sortBy: 'cpu' | 'gpu'
  health?: CollectionHealth | null
  clusterName: string
}) {
  const [filters, setFilters] = useState<Record<string, string>>({})
  const setFilter = (k: string, v: string) => setFilters((p) => ({ ...p, [k]: v }))

  const nodeName = (id: string) => {
    const n = nodes.find((x) => x.nodeId === id)
    return n?.hostname || n?.ip || id.slice(0, 12)
  }

  // 列定义
  const COLS = [
    { key: 'name', header: '进程名', getValue: (w: WorkerSnapshot) => w.processName || 'ray::?', right: false },
    { key: 'node', header: '节点', getValue: (w: WorkerSnapshot) => nodeName(w.nodeId), right: false },
    { key: 'pid', header: 'PID', getValue: (w: WorkerSnapshot) => String(w.pid), right: true },
    { key: 'cpu', header: 'CPU %', getValue: (w: WorkerSnapshot) => w.cpuPercent.toFixed(1), right: true },
    { key: 'mem', header: '内存', getValue: (w: WorkerSnapshot) => fmtBytes(w.memRss), right: true },
    { key: 'gpu', header: 'GPU', getValue: (w: WorkerSnapshot) => (w.gpuUsed > 0 ? String(w.gpuUsed) : '-'), right: true },
  ]
  const colGetters = Object.fromEntries(COLS.map((c) => [c.key, c.getValue]))

  const staleNodeIDs = useMemo(() => {
    const s = new Set<string>()
    if (health?.failedNodes) {
      for (const fn of health.failedNodes) {
        if (fn.currentStale) s.add(fn.nodeId)
      }
    }
    return s
  }, [health])

  const isStale = (w: WorkerSnapshot) => staleNodeIDs.has(w.nodeId)

  const sorted = useMemo(
    () =>
      [...workers].sort((a, b) => {
        if (sortBy === 'gpu') return (b.gpuUsed || 0) - (a.gpuUsed || 0)
        return (b.cpuPercent || 0) - (a.cpuPercent || 0)
      }),
    [workers, sortBy],
  )

  const filtered = useMemo(() => applyFilters(sorted, filters, colGetters), [sorted, filters])

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <CardTitle>
            Worker 进程 · 共 {filtered.length} / {workers.length} 个（按 {sortBy === 'cpu' ? 'CPU' : 'GPU'} 排序）
          </CardTitle>
          <ExportSnapshotButton
            filenameBase={`${clusterName}_进程`}
            headers={COLS.map((c) => c.header)}
            rows={filtered.map((w) => COLS.map((c) => c.getValue(w)))}
          />
        </div>
      </CardHeader>
      <CardContent>
        {workers.length === 0 ? (
          <div className="py-8 text-center text-xs text-muted-foreground">无 worker 进程</div>
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
              {filtered.map((w, i) => {
                const stale = isStale(w)
                return (
                  <TableRow key={`${w.nodeId}-${w.pid}-${i}`} className={stale ? 'opacity-60' : ''}>
                    <TableCell className="font-mono text-xs">
                      {w.processName || 'ray::?'}
                      {stale && (
                        <span
                          className="ml-1.5 rounded bg-orange-100 px-1 py-0.5 text-[10px] text-orange-600"
                          title="该节点本轮采集失败，当前显示最近一次成功数据"
                        >
                          未刷新
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{nodeName(w.nodeId)}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{w.pid}</TableCell>
                    <TableCell className="text-right">{w.cpuPercent.toFixed(1)}</TableCell>
                    <TableCell className="text-right">{fmtBytes(w.memRss)}</TableCell>
                    <TableCell className="text-right">{w.gpuUsed > 0 ? w.gpuUsed : '-'}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
