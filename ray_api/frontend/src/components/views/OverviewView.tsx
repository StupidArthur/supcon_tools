import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { fmtBytes, pct } from '@/lib/utils'
import type { ClusterMetric, NodeMetric, PerfMetrics } from '@/lib/api'

interface OverviewData {
  cluster: ClusterMetric
  nodes: NodeMetric[]
  nodeCount: number
  recentJobs: unknown[]
  updatedAt: number
}

export function OverviewView({ data, perf }: { data: OverviewData | null; perf: PerfMetrics | null }) {
  if (!data) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">暂无数据，请点击右上角“开始采集”</div>
  }
  const { cluster, nodes } = data

  // 实际占用（硬件视角）：汇总各节点
  const cpuUsedReal = nodes.reduce((s, n) => s + (n.cpu || 0), 0)
  const memUsedReal = nodes.reduce((s, n) => s + (n.memUsed || 0), 0)
  const memTotalReal = nodes.reduce((s, n) => s + (n.memTotal || 0), 0)
  const cpuTotalReal = nodes.reduce((s, n) => s + (n.gpuTotal > 0 ? 0 : 0), 0) // 占位，CPU总量以分配视角为准
  // GPU 实际利用率 Ray 接口无，留空
  const hasGpu = cluster.gpuTotal > 0 || nodes.some((n) => n.gpuTotal > 0)

  return (
    <div className="space-y-3.5">
      {/* 第一行：分配值（Ray 调度视角） */}
      <Card>
        <CardContent className="py-4">
          <div className="mb-3 text-xs font-medium text-muted-foreground">分配值（Ray 调度视角）</div>
          <div className="grid grid-cols-3 gap-6">
            <Metric label="CPU" used={cluster.cpuUsed} total={cluster.cpuTotal} unit="核" />
            <Metric label="内存" used={cluster.memUsed} total={cluster.memTotal} unit="GiB" />
            <Metric label="GPU" used={cluster.gpuUsed} total={cluster.gpuTotal} unit="张" />
          </div>
        </CardContent>
      </Card>

      {/* 第二行：实际占用（硬件视角） */}
      <Card>
        <CardContent className="py-4">
          <div className="mb-3 text-xs font-medium text-muted-foreground">实际占用（节点硬件视角）</div>
          <div className="grid grid-cols-3 gap-6">
            <Metric label="CPU 负载" used={cpuUsedReal} total={cpuTotalReal || cluster.cpuTotal} unit="核" real />
            <Metric
              label="内存"
              used={memUsedReal / 1024 / 1024 / 1024}
              total={memTotalReal / 1024 / 1024 / 1024}
              unit="GiB"
              real
            />
            <Metric label="GPU" used={NaN} total={NaN} unit="张" real empty={!hasGpu} />
          </div>
        </CardContent>
      </Card>

      <div className="px-1 text-xs text-muted-foreground">
        在线节点 {data.nodeCount} / 共 {nodes.length} 个
      </div>

      {/* 采集器自评估：生产环境跑起来后据此决策是否需改架构 */}
      {perf ? <PerfCard perf={perf} gzipSupported={cluster.gzipSupported} /> : null}
    </div>
  )
}

function PerfCard({ perf, gzipSupported }: { perf: PerfMetrics; gzipSupported: boolean }) {
  const riskVariant =
    perf.risk === 'danger' ? 'destructive' : perf.risk === 'warn' ? 'warning' : 'success'
  const riskText =
    perf.risk === 'danger'
      ? '危险：detail 采集耗时已接近采集周期，可能赶不上下一轮，建议改架构（detail 分批/按需）'
      : perf.risk === 'warn'
      ? '警告：存在慢请求或内存偏高，关注是否随节点数增长恶化'
      : '正常：当前负载健康'
  return (
    <Card>
      <CardContent className="py-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">采集器自评估</span>
          <Badge variant={riskVariant as 'success' | 'warning' | 'destructive'}>{perf.risk}</Badge>
        </div>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <PerfStat label="summary 耗时" value={`${perf.summaryMs} ms`} />
          <PerfStat label="detail 耗时" value={`${perf.detailMs} ms`} />
          <PerfStat label="节点详情阶段" value={`${perf.detailNodesMs} ms`} sub={`并发 ${perf.concurrency}`} />
          <PerfStat label="最慢单节点" value={`${perf.detailMaxNodeMs} ms`} sub={perf.slowNodeHost || perf.slowNodeId?.slice(0, 12) || '-'} />
          <PerfStat label="节点数" value={`${perf.nodeCount}`} />
          <PerfStat label="worker 进程" value={`${perf.workerCount}`} />
          <PerfStat label="Actor 数" value={`${perf.actorCount}`} />
          <PerfStat label="detail 请求数" value={`${perf.detailReqs}`} />
          <PerfStat label="进程内存" value={fmtBytes(perf.procMemBytes)} />
          <PerfStat label="goroutine" value={`${perf.procGoroutine}`} />
          <PerfStat
            label="HTTP 压缩"
            value={gzipSupported ? '✅ 已启用' : '❌ 不支持'}
            sub={gzipSupported ? 'Ray dashboard 返回 gzip' : '回退明文传输'}
          />
        </div>
        <div className="mt-3 text-xs text-muted-foreground">{riskText}</div>
      </CardContent>
    </Card>
  )
}

function PerfStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-semibold">{value}</div>
      {sub ? <div className="text-xs text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function Metric({
  label,
  used,
  total,
  unit,
  real,
  empty,
}: {
  label: string
  used: number
  total: number
  unit: string
  real?: boolean
  empty?: boolean
}) {
  if (empty) {
    return (
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-muted-foreground">-</div>
        <div className="mt-1 text-xs text-muted-foreground">无 GPU</div>
      </div>
    )
  }
  const p = pct(used, total)
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">
        {real ? used.toFixed(1) : used.toFixed(1)}
        <span className="ml-1 text-sm font-normal text-muted-foreground">/ {total.toFixed(1)} {unit}</span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
        <div className={`h-full rounded-full ${real ? 'bg-blue-500' : 'bg-primary'}`} style={{ width: `${p}%` }} />
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{p}%</div>
    </div>
  )
}

// fmtBytes 仅用于潜在调试，保留引用避免未使用告警
void fmtBytes
