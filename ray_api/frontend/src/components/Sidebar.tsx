import { cn } from '@/lib/utils'
import { AlertTriangle } from 'lucide-react'
import type { ClusterConfig, CollectorStatus } from '@/lib/api'

export type Selection =
  | { kind: 'global-alerts' }
  | { kind: 'cluster'; id: string }

// displayName 从 URL 提取 host:port 作为集群名。
function displayName(cl: ClusterConfig): string {
  const url = cl.platformUrl || ''
  if (!url) return cl.id
  return url.replace(/^https?:\/\//, '')
}

export function Sidebar({
  clusters,
  selection,
  statuses,
  globalAlertCount,
  onSelect,
}: {
  clusters: ClusterConfig[]
  selection: Selection
  statuses: Record<string, CollectorStatus>
  globalAlertCount: number
  onSelect: (s: Selection) => void
}) {
  return (
    <aside className="flex w-[208px] flex-shrink-0 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center gap-2 px-5">
        <div className="h-6 w-6 rounded-md bg-primary" />
        <span className="text-sm font-semibold">Ray 监控</span>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-2">
        {/* 全局报警 */}
        <button
          onClick={() => onSelect({ kind: 'global-alerts' })}
          className={cn(
            'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
            selection.kind === 'global-alerts'
              ? 'bg-secondary font-medium text-foreground'
              : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
          )}
        >
          <AlertTriangle className="h-4 w-4" />
          全局报警
          {globalAlertCount > 0 ? (
            <span className="ml-auto rounded-full bg-destructive px-1.5 text-xs text-white">{globalAlertCount}</span>
          ) : null}
        </button>

        <div className="my-1 px-3 text-[11px] font-medium text-muted-foreground">集群</div>

        {/* 集群列表（名 = URL 的 host:port） */}
        {clusters.map((cl) => {
          const st = statuses[cl.id]
          const dot = dotFor(st)
          const active = selection.kind === 'cluster' && selection.id === cl.id
          return (
            <button
              key={cl.id}
              onClick={() => onSelect({ kind: 'cluster', id: cl.id })}
              className={cn(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
                active ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
              )}
              title={cl.platformUrl}
            >
              <span className={cn('h-2 w-2 flex-shrink-0 rounded-full', dot)} />
              <span className="truncate">{displayName(cl)}</span>
            </button>
          )
        })}

        {clusters.length === 0 ? (
          <div className="px-3 py-2 text-xs text-muted-foreground">点击右上角"配置"添加集群</div>
        ) : null}
      </nav>
      <div className="px-5 py-3 text-[11px] text-muted-foreground/70">
        v0.92 designed by @yuzechao
      </div>
    </aside>
  )
}

// dotFor 根据采集状态返回状态点颜色。
function dotFor(st?: CollectorStatus): string {
  if (!st) return 'bg-muted-foreground'
  if (!st.running) return 'bg-muted-foreground'
  if (st.errCount > 0) return 'bg-red-500'
  return 'bg-green-500'
}
