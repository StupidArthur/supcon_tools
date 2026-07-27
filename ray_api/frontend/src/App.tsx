import { useEffect, useState, useCallback } from 'react'
import { Sidebar, type Selection } from '@/components/Sidebar'
import { TopBar } from '@/components/TopBar'
import { ConfigDialog } from '@/components/ConfigDialog'
import { ClusterControlDialog } from '@/components/ClusterControlDialog'
import { CollectionHealthNotice } from '@/components/CollectionHealthNotice'
import { OverviewView } from '@/components/views/OverviewView'
import { NodesView } from '@/components/views/NodesView'
import { WorkersView } from '@/components/views/WorkersView'
import { AlertsView } from '@/components/views/AlertsView'
import { APILogView } from '@/components/views/APILogView'
import {
  api,
  type ClusterConfig,
  type CollectorStatus,
  type GlobalPerf,
  type PerfMetrics,
  type Overview,
  type NodeMetric,
  type WorkerSnapshot,
  type CollectionHealth,
  type Config,
} from '@/lib/api'

type Tab = 'overview' | 'nodes' | 'workers' | 'alerts'

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'nodes', label: '节点' },
  { key: 'workers', label: '进程' },
  { key: 'alerts', label: '报警' },
]

export default function App() {
  const [clusters, setClusters] = useState<ClusterConfig[]>([])
  const [selection, setSelection] = useState<Selection>({ kind: 'global-alerts' })
  const [statuses, setStatuses] = useState<Record<string, CollectorStatus>>({})
  const [globalPerf, setGlobalPerf] = useState<GlobalPerf | null>(null)
  const [config, setConfig] = useState<Config | null>(null)
  const [sortBy, setSortBy] = useState<'cpu' | 'gpu'>('cpu')
  const [tab, setTab] = useState<Tab>('overview')
  const [showConfig, setShowConfig] = useState(false)
  const [showControl, setShowControl] = useState(false)
  const [running, setRunning] = useState(false)
  const [globalAlertCount, setGlobalAlertCount] = useState(0)
  const [lastRefreshed, setLastRefreshed] = useState<number>(0)
  const [now, setNow] = useState<number>(Date.now())

  // 按页数据（不再拉完整 Snapshot）
  const [overview, setOverview] = useState<Overview | null>(null)
  const [perf, setPerf] = useState<PerfMetrics | null>(null)
  const [nodes, setNodes] = useState<NodeMetric[]>([])
  const [workers, setWorkers] = useState<WorkerSnapshot[]>([])
  const [health, setHealth] = useState<CollectionHealth | null>(null)

  const clusterID = selection.kind === 'cluster' ? selection.id : ''

  // 轻量刷新：集群列表 + 状态 + 全局 perf + 告警计数 + 当前页数据
  const refresh = useCallback(async () => {
    try {
      const [ids, cfg, gp] = await Promise.all([api.listClusterIDs(), api.getConfig(), api.getGlobalPerf()])
      setGlobalPerf(gp)
      setConfig(cfg)
      if (cfg.sortBy === 'gpu') setSortBy('gpu')
      else setSortBy('cpu')
      setClusters(cfg.clusters || [])

      const stMap: Record<string, CollectorStatus> = {}
      let anyRunning = false
      await Promise.all(
        ids.map(async (id) => {
          const st = await api.getClusterStatus(id)
          stMap[id] = st
          if (st.running) anyRunning = true
        }),
      )
      setStatuses(stMap)
      setRunning(anyRunning)
      setGlobalAlertCount(await api.countAlerts(''))

      // 按当前页拉数据，不拉完整 Snapshot
      if (clusterID) {
        if (tab === 'overview') {
          const [ov, pf] = await Promise.all([api.getOverview(clusterID), api.getPerf(clusterID)])
          setOverview(ov)
          setPerf(pf)
        } else if (tab === 'nodes') {
          const [ns, h] = await Promise.all([api.getNodes(clusterID), api.getHealth(clusterID)])
          setNodes(ns ?? [])
          setHealth(h)
        } else if (tab === 'workers') {
          const [ws, ns, h] = await Promise.all([
            api.getWorkers(clusterID),
            api.getNodes(clusterID),
            api.getHealth(clusterID),
          ])
          setWorkers(ws ?? [])
          setNodes(ns ?? [])
          setHealth(h)
        }
        // alerts 页自己拉数据（AlertsView 内部有 5s 轮询）
      }

      setLastRefreshed(Date.now())
      api.logFrontendEvent(clusterID, '刷新', `页面刷新（当前页 ${tab}）`).catch(() => {})
    } catch {
      // Wails 未就绪
    }
  }, [clusterID, tab])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (!running) return
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [running, refresh])

  // 每秒更新一次"now"，让"最后刷新 Xs 前"显示走字
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const toggleSort = useCallback(async () => {
    const next: 'cpu' | 'gpu' = sortBy === 'cpu' ? 'gpu' : 'cpu'
    setSortBy(next)
    if (config) await api.saveConfig({ ...config, sortBy: next })
  }, [sortBy, config])

  // 切换集群/tab 时立即拉一次
  useEffect(() => {
    if (!clusterID) return
    if (tab === 'overview') {
      Promise.all([api.getOverview(clusterID), api.getPerf(clusterID)]).then(([ov, pf]) => {
        setOverview(ov)
        setPerf(pf)
        setLastRefreshed(Date.now())
        api.logFrontendEvent(clusterID, '切页', `切换到 ${tab} 页`).catch(() => {})
      }).catch(() => {})
    } else if (tab === 'nodes') {
      Promise.all([api.getNodes(clusterID), api.getHealth(clusterID)]).then(([ns, h]) => {
        setNodes(ns ?? [])
        setHealth(h)
        setLastRefreshed(Date.now())
        api.logFrontendEvent(clusterID, '切页', `切换到 ${tab} 页`).catch(() => {})
      }).catch(() => {})
    } else if (tab === 'workers') {
      Promise.all([api.getWorkers(clusterID), api.getNodes(clusterID), api.getHealth(clusterID)]).then(([ws, ns, h]) => {
        setWorkers(ws ?? [])
        setNodes(ns ?? [])
        setHealth(h)
        setLastRefreshed(Date.now())
        api.logFrontendEvent(clusterID, '切页', `切换到 ${tab} 页`).catch(() => {})
      }).catch(() => {})
    }
  }, [clusterID, tab])

  const title =
    selection.kind === 'global-alerts'
      ? '全局报警'
      : selection.kind === 'api-log'
        ? '接口日志'
        : clusters.find((c) => c.id === clusterID)?.platformUrl?.replace(/^https?:\/\//, '') || clusterID

  // "最后刷新 Xs 前" 文案
  const elapsedSec = lastRefreshed > 0 ? Math.max(0, Math.floor((now - lastRefreshed) / 1000)) : null

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <Sidebar
        clusters={clusters}
        selection={selection}
        statuses={statuses}
        globalAlertCount={globalAlertCount}
        onSelect={(s) => {
          setSelection(s)
          setTab('overview')
          if (s.kind === 'cluster') {
            api.logFrontendEvent(s.id, '切集群', `切换到集群 ${s.id}`).catch(() => {})
          } else if (s.kind === 'api-log') {
            api.logFrontendEvent('', '页面', '打开接口日志页').catch(() => {})
          } else if (s.kind === 'global-alerts') {
            api.logFrontendEvent('', '页面', '打开全局报警页').catch(() => {})
          }
        }}
      />
      <main className="flex flex-1 flex-col min-w-0">
        <TopBar
          title={title}
          running={running}
          globalPerf={globalPerf}
          sortBy={sortBy}
          onOpenControl={() => setShowControl(true)}
          onConfig={() => setShowConfig(true)}
          onToggleSort={toggleSort}
        />
        {selection.kind === 'cluster' ? (
          <>
            <div className="flex flex-shrink-0 items-center justify-between border-b border-border bg-card px-7">
              <div className="flex gap-1">
                {TABS.map((t) => (
                  <button
                    key={t.key}
                    onClick={() => setTab(t.key)}
                    className={`-mb-px border-b-2 px-3 py-2.5 text-sm transition-colors ${
                      tab === t.key
                        ? 'border-primary font-medium text-foreground'
                        : 'border-transparent text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {elapsedSec !== null && (
                <span className="py-2.5 text-xs text-muted-foreground">最后刷新 {elapsedSec}s 前</span>
              )}
            </div>
            <CollectionHealthNotice health={health} />
            <div className="flex-1 overflow-y-auto p-7">
              {tab === 'overview' && <OverviewView data={overview} perf={perf ?? null} />}
              {tab === 'nodes' && <NodesView nodes={nodes} sortBy={sortBy} clusterName={title} />}
              {tab === 'workers' && (
                <WorkersView workers={workers} nodes={nodes} sortBy={sortBy} health={health} clusterName={title} />
              )}
              {tab === 'alerts' && (
                <AlertsView clusterID={clusterID} clusterName={title} onJumpObject={() => setTab('nodes')} />
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 overflow-y-auto p-7">
            {selection.kind === 'global-alerts' && <AlertsView clusterID="" clusterName="" />}
            {selection.kind === 'api-log' && <APILogView />}
          </div>
        )}
      </main>
      {showConfig && config ? (
        <ConfigDialog config={config} onClose={() => { setShowConfig(false); refresh() }} />
      ) : null}
      {showControl ? (
        <ClusterControlDialog
          clusters={clusters}
          statuses={statuses}
          onClose={() => setShowControl(false)}
          onAfterAction={refresh}
        />
      ) : null}
    </div>
  )
}
