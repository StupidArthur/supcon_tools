import { useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtBytes, pct, FilterInput } from '@/lib/utils'
import type { NodeMetric } from '@/lib/api'

// 列定义：key = 列 ID，header = 表头文字，getValue = 取该列字符串值（用于 contains 筛）
const COLS = [
  { key: 'name', header: '节点名', getValue: (n: NodeMetric) => n.hostname || n.ip || n.nodeId.slice(0, 12) },
  { key: 'type', header: '类型', getValue: (n: NodeMetric) => (n.isHead ? 'Head' : 'Worker') },
  { key: 'cpu', header: 'CPU', getValue: (n: NodeMetric) => n.cpu.toFixed(1) },
  {
    key: 'mem',
    header: '内存',
    getValue: (n: NodeMetric) => `${fmtBytes(n.memUsed)} / ${fmtBytes(n.memTotal)} ${pct(n.memUsed, n.memTotal)}%`,
  },
  {
    key: 'gpu',
    header: 'GPU',
    getValue: (n: NodeMetric) => (n.gpuTotal > 0 ? `${n.gpuUsed}/${n.gpuTotal}` : '-'),
  },
  { key: 'state', header: '状态', getValue: (n: NodeMetric) => n.state },
]

export function NodesView({ nodes, sortBy }: { nodes: NodeMetric[]; sortBy: 'cpu' | 'gpu' }) {
  // 列筛选（contains，不区分大小写）
  const [filters, setFilters] = useState<Record<string, string>>({})
  const setFilter = (key: string, val: string) => setFilters((p) => ({ ...p, [key]: val }))

  // 排序：按 CPU 或 GPU 降序
  const sorted = useMemo(
    () =>
      [...nodes].sort((a, b) => {
        if (sortBy === 'gpu') return (b.gpuTotal || 0) - (a.gpuTotal || 0)
        return (b.cpu || 0) - (a.cpu || 0)
      }),
    [nodes, sortBy],
  )

  // 应用筛选
  const filtered = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => v.trim())
    if (active.length === 0) return sorted
    return sorted.filter((n) =>
      active.every(([k, v]) => {
        const col = COLS.find((c) => c.key === k)
        if (!col) return true
        return col.getValue(n).toLowerCase().includes(v.toLowerCase())
      }),
    )
  }, [sorted, filters])

  if (!nodes.length) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">暂无节点数据</div>
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          节点列表 · 共 {filtered.length} / {nodes.length} 个（按 {sortBy === 'cpu' ? 'CPU' : 'GPU'} 排序）
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              {COLS.map((c) => (
                <TableHead key={c.key} className={c.key === 'cpu' || c.key === 'mem' || c.key === 'gpu' ? 'text-right' : ''}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
            <TableRow>
              {COLS.map((c) => (
                <TableHead key={c.key} className={c.key === 'cpu' || c.key === 'mem' || c.key === 'gpu' ? 'text-right' : ''}>
                  <FilterInput
                    value={filters[c.key] || ''}
                    onChange={(v) => setFilter(c.key, v)}
                    placeholder="筛选"
                  />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((n) => (
              <TableRow key={n.nodeId}>
                <TableCell className="font-medium">
                  {n.hostname || n.ip || n.nodeId.slice(0, 12)}
                  {n.isPartial ? <Badge variant="warning" className="ml-2">半哑</Badge> : null}
                </TableCell>
                <TableCell>{n.isHead ? <Badge variant="primary">Head</Badge> : <Badge>Worker</Badge>}</TableCell>
                <TableCell className="text-right">{n.cpu.toFixed(1)}</TableCell>
                <TableCell className="text-right">
                  {fmtBytes(n.memUsed)} / {fmtBytes(n.memTotal)}
                  <span className="ml-1 text-xs text-muted-foreground">{pct(n.memUsed, n.memTotal)}%</span>
                </TableCell>
                <TableCell className="text-right">{n.gpuTotal > 0 ? `${n.gpuUsed}/${n.gpuTotal}` : '-'}</TableCell>
                <TableCell>
                  <Badge variant={n.state === 'ALIVE' ? 'success' : 'destructive'}>{n.state}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
