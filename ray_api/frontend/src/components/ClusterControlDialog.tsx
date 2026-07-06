import { Button } from '@/components/ui/button'
import { api, type ClusterConfig, type CollectorStatus } from '@/lib/api'

// ClusterControlDialog 集群操作弹窗：可逐集群启停监控，也可全部启停。
// 替换 TopBar 上的"开始/停止全部"切换按钮（点击这里弹窗更显式）。
export function ClusterControlDialog({
  clusters,
  statuses,
  onClose,
  onAfterAction,
}: {
  clusters: ClusterConfig[]
  statuses: Record<string, CollectorStatus>
  onClose: () => void
  // 启停后回调，让 App 立即刷新状态（不等 5s 轮询）
  onAfterAction: () => void
}) {
  // 操作单个集群：调 start/stop 后立即 refresh（不等 5s 轮询）
  const toggle = async (id: string, running: boolean) => {
    try {
      if (running) {
        await api.stopCluster(id)
      } else {
        await api.startCluster(id)
      }
      onAfterAction()
    } catch {
      // 失败交由主轮询显示红点
    }
  }

  const startAll = async () => {
    await api.startAll()
    onAfterAction()
  }

  const stopAll = async () => {
    await api.stopAll()
    onAfterAction()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="w-[520px] max-h-[85vh] overflow-y-auto rounded-xl bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-base font-semibold">集群操作</h2>

        <div className="mb-4 flex gap-2 border-b border-border pb-4">
          <Button size="sm" onClick={startAll}>
            全部开始
          </Button>
          <Button variant="destructive" size="sm" onClick={stopAll}>
            全部停止
          </Button>
        </div>

        {clusters.length === 0 ? (
          <div className="py-8 text-center text-xs text-muted-foreground">
            暂无集群，请到配置页添加
          </div>
        ) : (
          <div className="space-y-2">
            {clusters.map((cl) => {
              const st = statuses[cl.id]
              const isRunning = st?.running ?? false
              const errCount = st?.errCount ?? 0
              return (
                <div
                  key={cl.id}
                  className="flex items-center gap-3 rounded-md border border-border p-3"
                >
                  <span
                    className={dotClass(isRunning, errCount)}
                    title={dotTitle(isRunning, errCount)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-xs">
                      {cl.platformUrl.replace(/^https?:\/\//, '') || cl.id}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {isRunning
                        ? errCount > 0
                          ? `运行中 · ${errCount} 错误`
                          : '运行中'
                        : '已停止'}
                    </div>
                  </div>
                  {isRunning ? (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => toggle(cl.id, true)}
                    >
                      停止
                    </Button>
                  ) : (
                    <Button size="sm" onClick={() => toggle(cl.id, false)}>
                      开始
                    </Button>
                  )}
                </div>
              )
            })}
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </div>
  )
}

// dotClass 状态点颜色（与 Sidebar 保持一致：绿/红/灰）
function dotClass(running: boolean, errCount: number): string {
  if (!running) return 'h-2 w-2 flex-shrink-0 rounded-full bg-muted-foreground'
  if (errCount > 0) return 'h-2 w-2 flex-shrink-0 rounded-full bg-red-500'
  return 'h-2 w-2 flex-shrink-0 rounded-full bg-green-500'
}

function dotTitle(running: boolean, errCount: number): string {
  if (!running) return '已停止'
  if (errCount > 0) return `运行中 · ${errCount} 错误`
  return '运行中'
}
