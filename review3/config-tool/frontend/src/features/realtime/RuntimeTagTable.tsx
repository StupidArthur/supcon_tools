import { useCallback, useEffect, useMemo, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'

interface ForceEntry {
  mode: string
  value?: number
}

export function RuntimeTagTable() {
  const rawSnapshot = useRuntimeStore((s) => s.rawSnapshot)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const stale = useRuntimeStore((s) => s.stale)
  const apiHost = useRuntimeStore((s) => s.apiHost)
  const apiPort = useRuntimeStore((s) => s.apiPort)
  const [filter, setFilter] = useState('')
  const [forces, setForces] = useState<Record<string, ForceEntry>>({})

  const refreshForces = useCallback(async () => {
    try {
      const f = await realtimeProjectApi.getForces(apiHost, apiPort) as any
      setForces(f || {})
    } catch {
      // ignore
    }
  }, [apiHost, apiPort])

  useEffect(() => {
    if (connectionState === 'connected') void refreshForces()
  }, [connectionState, refreshForces])

  const tags = useMemo(() => {
    if (!rawSnapshot) return []
    const entries = Object.entries(rawSnapshot)
      .filter(([k]) => !k.startsWith('_') && k !== 'cycle_count' && k !== 'sim_time')
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => a.name.localeCompare(b.name))
    if (!filter) return entries
    const lower = filter.toLowerCase()
    return entries.filter((e) => e.name.toLowerCase().includes(lower))
  }, [rawSnapshot, filter])

  const handleForce = async (tag: string, mode: string, value?: number) => {
    try {
      await realtimeProjectApi.setForce(apiHost, apiPort, tag, mode, value)
      await refreshForces()
    } catch {
      // ignore
    }
  }

  const handleClearForce = async (tag: string) => {
    try {
      await realtimeProjectApi.clearForce(apiHost, apiPort, tag)
      await refreshForces()
    } catch {
      // ignore
    }
  }

  if (!rawSnapshot) {
    return (
      <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground" data-testid="tag-table-empty">
        未运行。启动实时工程后此处显示位号表。
      </div>
    )
  }

  const getUaValue = (name: string, runtimeValue: unknown): string => {
    const force = forces[name]
    if (!force || force.mode === 'follow') {
      return typeof runtimeValue === 'number' ? runtimeValue.toFixed(4) : String(runtimeValue ?? '—')
    }
    if (force.mode === 'zero') return '0.0000'
    if (force.mode === 'fixed' || force.mode === 'hold') {
      return typeof force.value === 'number' ? force.value.toFixed(4) : '—'
    }
    return typeof runtimeValue === 'number' ? runtimeValue.toFixed(4) : String(runtimeValue ?? '—')
  }

  const getForceLabel = (name: string): string => {
    const force = forces[name]
    if (!force) return '跟随'
    if (force.mode === 'zero') return '置零'
    if (force.mode === 'hold') return '保持'
    if (force.mode === 'fixed') return `固定(${force.value})`
    return '跟随'
  }

  return (
    <section className="space-y-2" data-testid="runtime-tag-table">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium">位号表</span>
        <span className="text-xs text-muted-foreground">({tags.length})</span>
        {connectionState === 'disconnected' ? (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">连接断开</span>
        ) : stale ? (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">数据已过期</span>
        ) : connectionState === 'connected' ? (
          <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-800">已连接</span>
        ) : null}
        <input
          type="text"
          placeholder="搜索位号..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto w-40 rounded border border-border bg-background px-2 py-0.5 text-xs"
          data-testid="tag-table-filter"
        />
      </div>
      <div className="max-h-96 overflow-y-auto rounded-md border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border">
              <th className="px-3 py-1.5 text-left font-medium">位号</th>
              <th className="px-3 py-1.5 text-right font-medium">运行值</th>
              <th className="px-3 py-1.5 text-right font-medium">UA输出</th>
              <th className="px-3 py-1.5 text-center font-medium">强制</th>
              <th className="px-3 py-1.5 text-center font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => (
              <tr key={tag.name} className="border-b border-border/50">
                <td className="px-3 py-1 font-mono">{tag.name}</td>
                <td className="px-3 py-1 text-right font-mono">
                  {typeof tag.value === 'number' ? tag.value.toFixed(4) : String(tag.value ?? '—')}
                </td>
                <td className="px-3 py-1 text-right font-mono">
                  {getUaValue(tag.name, tag.value)}
                </td>
                <td className="px-3 py-1 text-center">
                  <span className={forces[tag.name] ? 'text-amber-700' : 'text-muted-foreground'}>
                    {getForceLabel(tag.name)}
                  </span>
                </td>
                <td className="px-3 py-1 text-center">
                  <div className="flex items-center justify-center gap-0.5">
                    {forces[tag.name] ? (
                      <button
                        type="button"
                        onClick={() => void handleClearForce(tag.name)}
                        className="rounded px-1 py-0.5 text-xs text-muted-foreground hover:bg-secondary"
                        title="恢复跟随"
                      >
                        ↺
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => void handleForce(tag.name, 'hold', typeof tag.value === 'number' ? tag.value : 0)}
                          className="rounded px-1 py-0.5 text-xs hover:bg-secondary"
                          title="保持当前值"
                        >
                          H
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleForce(tag.name, 'zero')}
                          className="rounded px-1 py-0.5 text-xs hover:bg-secondary"
                          title="置零"
                        >
                          0
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const v = prompt('固定值：', '0')
                            if (v !== null) void handleForce(tag.name, 'fixed', parseFloat(v) || 0)
                          }}
                          className="rounded px-1 py-0.5 text-xs hover:bg-secondary"
                          title="固定值"
                        >
                          F
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
