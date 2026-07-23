import { useCallback, useEffect, useState } from 'react'
import { realtimeRuntimeApi } from '../../lib/api'

interface RunMeta {
  sessionId: string
  projectId?: string
  projectName?: string
  runtimeRevision?: string
  startedAt?: string
  tags?: string[]
}

export function RunHistoryPanel() {
  const [runs, setRuns] = useState<RunMeta[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const r = await realtimeRuntimeApi.listRunHistory() as any
      setRuns(Array.isArray(r) ? r : [])
    } catch (e: any) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleDelete = async (sessionId: string) => {
    setError(null)
    try {
      await realtimeRuntimeApi.deleteRunHistory(sessionId)
      await refresh()
    } catch (e: any) {
      setError(String(e))
    }
  }

  return (
    <section className="space-y-2" data-testid="run-history-panel">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium">历史运行</span>
        <span className="text-xs text-muted-foreground">({runs.length})</span>
        <button type="button" onClick={() => void refresh()} className="ml-auto rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary">
          刷新
        </button>
      </div>
      {runs.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          暂无归档运行（启动工程时开启归档以记录）
        </div>
      ) : (
        <div className="space-y-1">
          {runs.map((r) => (
            <div key={r.sessionId} className="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-xs">
              <span className="font-mono">{r.sessionId.slice(0, 8)}</span>
              <span>{r.projectName || r.projectId || '—'}</span>
              <span className="text-muted-foreground">版本 {r.runtimeRevision || '—'}</span>
              <span className="text-muted-foreground">{r.startedAt || ''}</span>
              <span className="text-muted-foreground">{r.tags?.length || 0} tag</span>
              <button
                type="button"
                onClick={() => void handleDelete(r.sessionId)}
                className="ml-auto text-muted-foreground hover:text-destructive"
              >
                删除
              </button>
            </div>
          ))}
        </div>
      )}
      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">{error}</div>
      ) : null}
    </section>
  )
}
