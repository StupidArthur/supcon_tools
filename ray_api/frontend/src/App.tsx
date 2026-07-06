import { useEffect, useState, useCallback } from 'react'
import { Sidebar, type Selection } from '@/components/Sidebar'
import { TopBar } from '@/components/TopBar'
import { ConfigDialog } from '@/components/ConfigDialog'
import { ClusterControlDialog } from '@/components/ClusterControlDialog'
import { OverviewView } from '@/components/views/OverviewView'
import { NodesView } from '@/components/views/NodesView'
import { WorkersView } from '@/components/views/WorkersView'
import { ActorsView } from '@/components/views/ActorsView'
import { JobsView } from '@/components/views/JobsView'
import { AlertsView } from '@/components/views/AlertsView'
import {
  api,
  type ClusterConfig,
  type CollectorStatus,
  type GlobalPerf,
  type PerfMetrics,
  type Snapshot,
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
  const [snapshots, setSnapshots] = useState<Record<string, Snapshot | null>>({})
  const [perfs, setPerfs] = useState<Record<string, PerfMetrics>>({})
  const [globalPerf, setGlobalPerf] = useState<GlobalPerf | null>(null)
  const [config, setConfig] = useState<Config | null>(null)
  const [sortBy, setSortBy] = useState<'cpu' | 'gpu'>('cpu')
  const [tab, setTab] = useState<Tab>('overview')
  const [showConfig, setShowConfig] = useState(false)
  const [showControl, setShowControl] = useState(false)
  const [running, setRunning] = useState(false)
  const [globalAlertCount, setGlobalAlertCount] = useState(0)

  // 当前选中集群 ID（提前算，供 refresh 与渲染共用）
  const clusterID = selection.kind === 'cluster' ? selection.id : ''

  const refresh = useCallback(async () => {
    try {
      // 轻量：集群列表 + 全局 perf + 配置
      const [ids, cfg, gp] = await Promise.all([api.listClusterIDs(), api.getConfig(), api.getGlobalPerf()])
      setGlobalPerf(gp)
      setConfig(cfg)
      if (cfg.sortBy === 'gpu') setSortBy('gpu')
      else setSortBy('cpu')
      setClusters(cfg.clusters || [])

      // 每个集群只拉轻量 status（状态点用），不拉全量快照——避免 N 集群 × 大对象卡前端
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

      // 只拉当前选中集群的全量快照 + perf（用户在看的那一个）
      if (clusterID) {
        const [snap, pf] = await Promise.all([api.getSnapshot(clusterID), api.getPerf(clusterID)])
        setSnapshots((prev) => ({ ...prev, [clusterID]: snap }))
        setPerfs((prev) => ({ ...prev, [clusterID]: pf }))
      }
      // 全局告警计数（侧边栏角标）
      setGlobalAlertCount(await api.countAlerts(''))
    } catch {
      // Wails 未就绪
    }
  }, [clusterID])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 运行中定时刷新
  useEffect(() => {
    if (!running) return
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [running, refresh])

  const toggleSort = useCallback(async () => {
    const next: 'cpu' | 'gpu' = sortBy === 'cpu' ? 'gpu' : 'cpu'
    setSortBy(next)
    if (config) await api.saveConfig({ ...config, sortBy: next })
  }, [sortBy, config])

  // 当前选中集群的数据
  const snap = clusterID ? snapshots[clusterID] : null
  const perf = clusterID ? perfs[clusterID] : null

  // 切换集群时立即拉一次该集群快照（不等下个 5 秒 tick）
  useEffect(() => {
    if (clusterID) {
      Promise.all([api.getSnapshot(clusterID), api.getPerf(clusterID)]).then(([snap2, pf]) => {
        setSnapshots((prev) => ({ ...prev, [clusterID]: snap2 }))
        setPerfs((prev) => ({ ...prev, [clusterID]: pf }))
      }).catch(() => {})
    }
  }, [clusterID])

  const title =
    selection.kind === 'global-alerts'
      ? '全局报警'
      : clusters.find((c) => c.id === clusterID)?.platformUrl?.replace(/^https?:\/\//, '') || clusterID

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
            {/* tab 栏 */}
            <div className="flex flex-shrink-0 gap-1 border-b border-border bg-card px-7">
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
            <div className="flex-1 overflow-y-auto p-7">
              {tab === 'overview' && <OverviewView data={snap ? buildOverview(snap) : null} perf={perf ?? null} />}
              {tab === 'nodes' && <NodesView nodes={snap?.nodes ?? []} sortBy={sortBy} />}
              {tab === 'workers' && (
                <WorkersView workers={snap?.workers ?? []} nodes={snap?.nodes ?? []} sortBy={sortBy} />
              )}
              {tab === 'alerts' && (
                <AlertsView clusterID={clusterID} onJumpObject={() => setTab('nodes')} />
              )}
            </div>
          </>
        ) : (
          /* 全局报警视图（所有集群） */
          <div className="flex-1 overflow-y-auto p-7">
            <AlertsView clusterID="" />
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

// 概览数据由快照聚合
function buildOverview(snap: Snapshot) {
  let nodeCount = 0
  for (const n of snap.nodes) if (n.state === 'ALIVE') nodeCount++
  return {
    cluster: snap.cluster,
    nodes: snap.nodes,
    nodeCount,
    recentJobs: snap.jobs ?? [],
    updatedAt: Date.now(),
  }
}
