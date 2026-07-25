import { useState, useEffect, useRef } from 'react'

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
  staleWorkerCount: number
  staleActorCount: number
  clusterDataStale: boolean
  jobsDataStale: boolean
  lastStorageErrorTs: number
  lastStorageError: string
  failedNodes: NodeCollectionState[]
}

export type NoticeLevel = 'active' | 'recent' | 'storage' | null

export function getCollectionNotice(health: CollectionHealth | undefined | null, now: number): NoticeLevel {
  if (!health) return null
  if (health.currentIncomplete) return 'active'
  if (health.lastStorageError && health.lastStorageErrorTs > 0) return 'storage'
  if (health.lastIncompleteTs > 0 && now - health.lastIncompleteTs <= 60_000) return 'recent'
  return null
}

function fmtTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

export function CollectionHealthNotice({ health }: { health: CollectionHealth | undefined | null }) {
  const [now, setNow] = useState(Date.now())
  const [expanded, setExpanded] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const level = getCollectionNotice(health, now)

  useEffect(() => {
    if (level === 'recent') {
      timerRef.current = setInterval(() => setNow(Date.now()), 1000)
      return () => {
        if (timerRef.current) clearInterval(timerRef.current)
      }
    }
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [level])

  if (!level || !health) return null

  if (level === 'storage') {
    return (
      <div className="mx-7 mt-3 rounded-md border border-yellow-300 bg-yellow-50 px-4 py-2.5 text-xs text-yellow-800">
        当前数据可以显示，但历史数据写入失败。请检查数据库路径、磁盘空间或文件权限。
      </div>
    )
  }

  if (level === 'recent') {
    return (
      <div className="mx-7 mt-3 rounded-md border border-yellow-200 bg-yellow-50/60 px-4 py-2 text-xs text-yellow-700">
        过去 1 分钟内曾发生节点详情采集失败，当前已恢复，列表已更新为最新数据。
      </div>
    )
  }

  const noCacheNodes = health.failedNodes.filter((n) => !n.hasCachedData)

  return (
    <div className="mx-7 mt-3 rounded-md border border-orange-300 bg-orange-50 px-4 py-2.5 text-xs text-orange-800">
      <div className="flex items-center justify-between">
        <span>
          部分节点的进程数据暂未更新，当前列表中包含最近一次成功采集的数据。
          失败节点：{health.failedNodeCount}/{health.totalNodeCount}；沿用进程：{health.staleWorkerCount}；最近失败：{fmtTime(health.lastIncompleteTs)}。
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="ml-2 shrink-0 text-orange-600 underline hover:text-orange-800"
        >
          {expanded ? '收起' : '详情'}
        </button>
      </div>
      {noCacheNodes.length > 0 && (
        <div className="mt-1 text-orange-700">
          其中 {noCacheNodes.length} 个节点暂无可用的历史进程数据。
        </div>
      )}
      {expanded && (
        <div className="mt-2 space-y-1 border-t border-orange-200 pt-2">
          {health.failedNodes.map((n) => (
            <div key={n.nodeId} className="flex gap-3">
              <span className="font-mono">{n.nodeName || n.nodeId.slice(0, 12)}</span>
              <span>连续失败 {n.consecutiveFailures} 次</span>
              <span>最近失败 {fmtTime(n.lastFailureTs)}</span>
              <span>{n.hasCachedData ? `沿用 ${n.reusedWorkerCount}W/${n.reusedActorCount}A` : '无历史数据'}</span>
              {n.lastError && <span className="text-orange-600" title={n.lastError}>{n.lastError.slice(0, 60)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
