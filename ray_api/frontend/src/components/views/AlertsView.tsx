import { useEffect, useState, useRef, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtDateTime, FilterInput, applyFilters } from '@/lib/utils'
import { api, type Alert } from '@/lib/api'

// stateVariant 报警状态对应的 badge 样式。
function stateVariant(a: Alert): 'destructive' | 'warning' | 'success' | 'primary' {
  if (a.recovered && a.acknowledged) return 'success'
  if (a.recovered) return 'warning'
  if (a.acknowledged) return 'primary'
  return 'destructive'
}

function stateText(a: Alert): string {
  if (a.recovered && a.acknowledged) return '已消除'
  if (a.recovered) return '已恢复-未确认'
  if (a.acknowledged) return '报警-已确认'
  return '报警-未确认'
}

export function AlertsView({
  clusterID,
  onJumpObject,
}: {
  clusterID: string
  onJumpObject?: () => void
}) {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [showNode, setShowNode] = useState(true)
  const [showWorker, setShowWorker] = useState(true)
  const [menu, setMenu] = useState<{ x: number; y: number; alert: Alert } | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const setFilter = (k: string, v: string) => setFilters((p) => ({ ...p, [k]: v }))
  const menuRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    try {
      const res = await api.listAlerts(clusterID)
      setAlerts(res || [])
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [clusterID])

  useEffect(() => {
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const onContextMenu = (e: React.MouseEvent, a: Alert) => {
    e.preventDefault()
    setMenu({ x: e.clientX, y: e.clientY, alert: a })
  }

  const ack = async (a: Alert) => {
    await api.ackAlert(a.id)
    setMenu(null)
    load()
  }

  const copyInfo = (a: Alert) => {
    const text = `[告警] ${a.objectName} ${a.metric}=${a.lastValue.toFixed(1)}% (阈值${a.threshold}%) 状态:${stateText(a)} 集群:${a.clusterId} 触发:${fmtDateTime(a.firstTriggerTs)}`
    navigator.clipboard?.writeText(text)
    setMenu(null)
  }

  const showCluster = clusterID === ''

  // 列定义（动态：全局视图多一列"集群"）
  const COLS = useMemo(
    () => [
      ...(showCluster
        ? [{ key: 'cluster', header: '集群', getValue: (a: Alert) => a.clusterName || a.clusterId, right: false }]
        : []),
      { key: 'node', header: '节点', getValue: (a: Alert) => a.nodeName || '-', right: false },
      { key: 'object', header: '对象', getValue: (a: Alert) => a.objectName, right: false },
      {
        key: 'type',
        header: '类型',
        getValue: (a: Alert) => (a.objectType === 'node' ? '节点' : '进程'),
        right: false,
      },
      { key: 'metric', header: '指标', getValue: (a: Alert) => a.metric.toUpperCase(), right: false },
      { key: 'value', header: '实际值', getValue: (a: Alert) => `${a.lastValue.toFixed(1)}%`, right: true },
      {
        key: 'threshold',
        header: '阈值',
        getValue: (a: Alert) => `${a.threshold}%`,
        right: true,
      },
      { key: 'state', header: '状态', getValue: (a: Alert) => stateText(a), right: false },
      { key: 'time', header: '触发时间', getValue: (a: Alert) => fmtDateTime(a.firstTriggerTs), right: false },
    ],
    [showCluster],
  )
  const colGetters = Object.fromEntries(COLS.map((c) => [c.key, c.getValue]))

  // checkbox 过滤（节点/进程）
  const byType = alerts.filter((a) => (a.objectType === 'node' ? showNode : showWorker))
  // 列头 contains 过滤
  const visible = useMemo(() => applyFilters(byType, filters, colGetters), [byType, filters, colGetters])

  return (
    <div className="space-y-3.5">
      {/* checkbox：显示节点报警 / 显示进程报警 */}
      <div className="flex items-center gap-4 px-1 text-sm">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={showNode} onChange={(e) => setShowNode(e.target.checked)} />
          节点报警
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={showWorker} onChange={(e) => setShowWorker(e.target.checked)} />
          进程报警
        </label>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            报警 · {visible.length} 条
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              (clusterID={clusterID || '全局'}, 共{alerts.length}条)
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {visible.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">暂无报警</div>
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
                {visible.map((a) => (
                  <TableRow key={a.id} onContextMenu={(e) => onContextMenu(e, a)} className="cursor-context-menu">
                    {COLS.map((c) => {
                      if (c.key === 'cluster') {
                        return <TableCell key={c.key} className="text-xs text-muted-foreground">{a.clusterName || a.clusterId}</TableCell>
                      }
                      if (c.key === 'node') {
                        return <TableCell key={c.key} className="text-xs text-muted-foreground">{a.nodeName || '-'}</TableCell>
                      }
                      if (c.key === 'object') {
                        return <TableCell key={c.key} className="font-mono text-xs">{a.objectName}</TableCell>
                      }
                      if (c.key === 'type') {
                        return <TableCell key={c.key}>{a.objectType === 'node' ? '节点' : '进程'}</TableCell>
                      }
                      if (c.key === 'metric') {
                        return <TableCell key={c.key}>{a.metric.toUpperCase()}</TableCell>
                      }
                      if (c.key === 'value') {
                        return <TableCell key={c.key} className="text-right">{a.lastValue.toFixed(1)}%</TableCell>
                      }
                      if (c.key === 'threshold') {
                        return <TableCell key={c.key} className="text-right text-muted-foreground">{a.threshold}%</TableCell>
                      }
                      if (c.key === 'state') {
                        return <TableCell key={c.key}><Badge variant={stateVariant(a)}>{stateText(a)}</Badge></TableCell>
                      }
                      if (c.key === 'time') {
                        return <TableCell key={c.key} className="text-xs text-muted-foreground">{fmtDateTime(a.firstTriggerTs)}</TableCell>
                      }
                      return null
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 右键菜单 */}
      {menu ? (
        <div
          ref={menuRef}
          className="fixed z-50 min-w-[140px] rounded-md border border-border bg-card py-1 shadow-lg"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button className="flex w-full items-center px-3 py-1.5 text-sm hover:bg-secondary" onClick={() => ack(menu.alert)}>
            确认报警
          </button>
          <button className="flex w-full items-center px-3 py-1.5 text-sm hover:bg-secondary" onClick={() => { onJumpObject?.(); setMenu(null) }}>
            查看对象
          </button>
          <button className="flex w-full items-center px-3 py-1.5 text-sm hover:bg-secondary" onClick={() => copyInfo(menu.alert)}>
            复制信息
          </button>
        </div>
      ) : null}
    </div>
  )
}
