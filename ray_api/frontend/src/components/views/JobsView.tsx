import { useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtDateTime, FilterInput, applyFilters } from '@/lib/utils'
import { api, type JobSnapshot } from '@/lib/api'

export function JobsView({ clusterID, jobs }: { clusterID: string; jobs: JobSnapshot[] }) {
  const [history, setHistory] = useState<JobSnapshot[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const setFilter = (k: string, v: string) => setFilters((p) => ({ ...p, [k]: v }))

  const statusVariant = (s: string) =>
    s === 'RUNNING' ? 'primary' : s === 'FAILED' ? 'destructive' : 'success'

  // 查询近 24 小时全部作业历史
  const loadHistory = () => {
    const to = Date.now()
    const from = to - 24 * 3600 * 1000
    api.getJobHistory(clusterID, { from, to }, '').then(setHistory)
  }

  const COLS = [
    { key: 'id', header: 'Job ID', getValue: (j: JobSnapshot) => j.jobId, right: false },
    { key: 'status', header: '状态', getValue: (j: JobSnapshot) => j.status, right: false },
    { key: 'start', header: '启动', getValue: (j: JobSnapshot) => fmtDateTime(j.startTime), right: false },
    { key: 'end', header: '结束', getValue: (j: JobSnapshot) => fmtDateTime(j.endTime), right: false },
    { key: 'error', header: '错误', getValue: (j: JobSnapshot) => j.errorType || '-', right: false },
    { key: 'entry', header: '入口', getValue: (j: JobSnapshot) => j.entry, right: false },
  ]
  const colGetters = Object.fromEntries(COLS.map((c) => [c.key, c.getValue]))
  const filtered = useMemo(() => applyFilters(jobs, filters, colGetters), [jobs, filters])

  // 历史表筛选（独立 state，不与当前作业混）
  const [histFilters, setHistFilters] = useState<Record<string, string>>({})
  const setHistFilter = (k: string, v: string) => setHistFilters((p) => ({ ...p, [k]: v }))
  const HIST_COLS = [
    { key: 'ts', header: '时间', getValue: (j: JobSnapshot) => fmtDateTime(j.ts) },
    { key: 'id', header: 'Job ID', getValue: (j: JobSnapshot) => j.jobId },
    { key: 'status', header: '状态', getValue: (j: JobSnapshot) => j.status },
    { key: 'error', header: '错误', getValue: (j: JobSnapshot) => j.errorType || '-' },
  ]
  const histColGetters = Object.fromEntries(HIST_COLS.map((c) => [c.key, c.getValue]))
  const filteredHist = useMemo(() => applyFilters(history, histFilters, histColGetters), [history, histFilters])

  return (
    <div className="space-y-3.5">
      <Card>
        <CardHeader>
          <CardTitle>当前作业 · 共 {filtered.length} / {jobs.length} 个</CardTitle>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">无作业</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  {COLS.map((c) => (
                    <TableHead key={c.key}>{c.header}</TableHead>
                  ))}
                </TableRow>
                <TableRow>
                  {COLS.map((c) => (
                    <TableHead key={c.key}>
                      <FilterInput value={filters[c.key] || ''} onChange={(v) => setFilter(c.key, v)} />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((j) => (
                  <TableRow key={j.jobId}>
                    <TableCell className="font-mono text-xs">{j.jobId}</TableCell>
                    <TableCell><Badge variant={statusVariant(j.status)}>{j.status}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDateTime(j.startTime)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDateTime(j.endTime)}</TableCell>
                    <TableCell className="max-w-[140px] truncate text-xs text-destructive">{j.errorType || '-'}</TableCell>
                    <TableCell className="max-w-[300px] truncate text-xs text-muted-foreground">{j.entry}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>历史查询 · 近 24h</CardTitle>
          <Button variant="outline" size="sm" onClick={loadHistory}>查询</Button>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">点击"查询"加载历史作业快照</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  {HIST_COLS.map((c) => (
                    <TableHead key={c.key}>{c.header}</TableHead>
                  ))}
                </TableRow>
                <TableRow>
                  {HIST_COLS.map((c) => (
                    <TableHead key={c.key}>
                      <FilterInput value={histFilters[c.key] || ''} onChange={(v) => setHistFilter(c.key, v)} />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredHist.map((j, i) => (
                  <TableRow key={`${j.jobId}-${j.ts}-${i}`}>
                    <TableCell className="text-xs text-muted-foreground">{fmtDateTime(j.ts)}</TableCell>
                    <TableCell className="font-mono text-xs">{j.jobId}</TableCell>
                    <TableCell><Badge variant={statusVariant(j.status)}>{j.status}</Badge></TableCell>
                    <TableCell className="text-xs text-destructive">{j.errorType || '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
