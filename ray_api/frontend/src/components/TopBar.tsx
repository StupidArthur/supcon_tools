import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Settings, ArrowUpDown, ListChecks } from 'lucide-react'
import type { GlobalPerf } from '@/lib/api'

export function TopBar({
  title,
  running,
  globalPerf,
  sortBy,
  onOpenControl,
  onConfig,
  onToggleSort,
}: {
  title: string
  running: boolean
  globalPerf: GlobalPerf | null
  sortBy: 'cpu' | 'gpu'
  onOpenControl: () => void
  onConfig: () => void
  onToggleSort: () => void
}) {
  return (
    <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-border bg-card px-7">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold">{title}</h1>
        {running ? (
          <Badge variant="success" className="gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-green-500" /> 采集中
          </Badge>
        ) : (
          <Badge variant="outline" className="gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" /> 已停止
          </Badge>
        )}
        {globalPerf ? (
          <span className="text-xs text-muted-foreground">
            {globalPerf.runningClusters}/{globalPerf.clusterCount} 集群 · {globalPerf.totalNodes} 节点 ·{' '}
            {globalPerf.clustersWithError} 错误
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onToggleSort} title="切换列表排序字段">
          <ArrowUpDown className="h-3.5 w-3.5" /> 排序: {sortBy === 'cpu' ? 'CPU' : 'GPU'}
        </Button>
        <Button variant="outline" size="sm" onClick={onConfig}>
          <Settings className="h-3.5 w-3.5" /> 配置
        </Button>
        <Button variant="outline" size="sm" onClick={onOpenControl} title="逐集群启停 + 全部启停">
          <ListChecks className="h-3.5 w-3.5" /> 操作
        </Button>
      </div>
    </header>
  )
}
