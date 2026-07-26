import { useEffect, useState } from 'react'

export interface NodeCollectionState {
  nodeId: string
  nodeName: string
  lastAttemptTs: number
  lastSuccessTs: number
  lastFailureTs: number
  consecutiveFailures: number
  lastError: string
  currentStale: boolean
  hasCachedData: boolean
  reusedWorkerCount: number
  reusedActorCount: number
}

export interface CollectionHealth {
  lastDetailAttemptTs: number
  lastCompleteDetailSuccessTs: number
  lastIncompleteTs: number
  currentIncomplete: boolean
  totalNodeCount: number
  freshNodeCount: number
  failedNodeCount: number
  staleNodeCount: number
  missingNodeCount: number
  staleWorkerCount: number
  staleActorCount: number
  clusterDataStale: boolean
  jobsDataStale: boolean
  currentStorageError: boolean
  lastStorageErrorTs: number
  lastStorageError: string
  failedNodes: NodeCollectionState[]
}

export type NoticeKind = 'node-detail' | 'cluster' | 'jobs' | 'storage' | 'recent-recovered'

export function getCollectionNotices(
  health: CollectionHealth | undefined | null,
  now: number,
): NoticeKind[] {
  if (!health) return []

  const notices: NoticeKind[] = []
  if (health.failedNodeCount > 0) notices.push('node-detail')
  if (health.clusterDataStale) notices.push('cluster')
  if (health.jobsDataStale) notices.push('jobs')
  if (health.currentStorageError) notices.push('storage')
  if (
    !health.currentIncomplete
    && health.lastIncompleteTs > 0
    && now - health.lastIncompleteTs <= 60_000
  ) {
    notices.push('recent-recovered')
  }
  return notices
}

export function startRecentTimer(
  onTick: () => void,
  setTimer: typeof setInterval = setInterval,
  clearTimer: typeof clearInterval = clearInterval,
): () => void {
  const timer = setTimer(onTick, 1000)
  return () => clearTimer(timer)
}

function fmtTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

export function CollectionHealthNotice({ health }: { health: CollectionHealth | undefined | null }) {
  const [now, setNow] = useState(Date.now())
  const [expanded, setExpanded] = useState(false)
  const notices = getCollectionNotices(health, now)
  const needsRecentTimer = notices.includes('recent-recovered')

  useEffect(() => {
    if (!needsRecentTimer) return
    return startRecentTimer(() => setNow(Date.now()))
  }, [needsRecentTimer])

  if (!health || notices.length === 0) return null

  return (
    <div className="mx-7 mt-3 space-y-1.5 rounded-md border border-orange-300 bg-orange-50 px-4 py-2.5 text-xs text-orange-800">
      {notices.includes('node-detail') && (
        <div>
          {health.staleNodeCount > 0 && (
            <div>
              部分节点的进程数据暂未更新，当前列表中包含最近一次成功采集的数据。
              失败节点：{health.failedNodeCount}/{health.totalNodeCount}；沿用节点：{health.staleNodeCount}；
              沿用进程：{health.staleWorkerCount}；最近失败：{fmtTime(health.lastIncompleteTs)}。
            </div>
          )}
          {health.missingNodeCount > 0 && (
            <div>
              其中 {health.missingNodeCount} 个节点暂无可用的历史进程数据，该节点的进程未显示。
            </div>
          )}
          {health.failedNodes.length > 0 && (
            <>
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-orange-600 underline hover:text-orange-800"
              >
                {expanded ? '收起节点详情' : '查看节点详情'}
              </button>
              {expanded && (
                <div className="mt-1 space-y-1 border-t border-orange-200 pt-1">
                  {health.failedNodes.map((node) => (
                    <div key={node.nodeId} className="flex flex-wrap gap-3">
                      <span className="font-mono">{node.nodeName || node.nodeId.slice(0, 12)}</span>
                      <span>连续失败 {node.consecutiveFailures} 次</span>
                      <span>{node.hasCachedData ? `沿用 ${node.reusedWorkerCount}W/${node.reusedActorCount}A` : '无历史数据'}</span>
                      {node.lastError && <span title={node.lastError}>{node.lastError.slice(0, 60)}</span>}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
      {notices.includes('cluster') && (
        <div>集群汇总指标暂未更新，当前显示最近一次成功采集的数据。</div>
      )}
      {notices.includes('jobs') && (
        <div>作业列表暂未更新，当前显示最近一次成功采集的数据。</div>
      )}
      {notices.includes('storage') && (
        <div>当前数据可以显示，但历史数据写入失败。请检查数据库路径、磁盘空间或文件权限。</div>
      )}
      {notices.includes('recent-recovered') && (
        <div>过去 1 分钟内曾发生数据采集不完整，当前已恢复。</div>
      )}
    </div>
  )
}
