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
  const [validTags, setValidTags] = useState<string[] | null>(null)
  const [forceError, setForceError] = useState<string | null>(null)

  const refreshForces = useCallback(async () => {
    try {
      const state = await realtimeProjectApi.getForces(apiHost, apiPort) as any
      setForces(state?.forces || {})
      if (Array.isArray(state?.tags)) setValidTags(state.tags)
    } catch (e: any) {
      setForceError(String(e))
    }
  }, [apiHost, apiPort])

  useEffect(() => {
    if (connectionState !== 'connected') return
    void refreshForces()
    const id = setInterval(() => void refreshForces(), 2000)
    return () => clearInterval(id)
  }, [connectionState, refreshForces])

  const tags = useMemo(() => {
    if (!rawSnapshot) return []
    const allowed = validTags ? new Set(validTags) : null
    const entries = Object.entries(rawSnapshot)
      .filter(([k, v]) => typeof v === 'number' && (allowed === null || allowed.has(k)))
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => a.name.localeCompare(b.name))
    if (!filter) return entries
    const lower = filter.toLowerCase()
    return entries.filter((e) => e.name.toLowerCase().includes(lower))
  }, [rawSnapshot, filter, validTags])

  const handleForce = async (tag: string, mode: string, value?: number, duration?: number) => {
    setForceError(null)
    try {
      await realtimeProjectApi.setForce(apiHost, apiPort, tag, mode, value, duration)
      await refreshForces()
    } catch (e: any) {
      setForceError(String(e))
    }
  }

  const handleClearForce = async (tag: string) => {
    setForceError(null)
    try {
      await realtimeProjectApi.clearForce(apiHost, apiPort, tag)
      await refreshForces()
    } catch (e: any) {
      setForceError(String(e))
    }
  }

  const parseDuration = (input: string): number | undefined | null => {
    if (input.trim() === '') return undefined
    const n = Number(input)
    if (!Number.isFinite(n) || n <= 0) return null
    return n
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
              <th className="px-3 py-1.5 text-right font-medium">预计 UA 输出</th>
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
                          onClick={() => {
                            const d = prompt('持续时间（秒，留空=永久）：', '')
                            if (d === null) return
                            const dur = parseDuration(d)
                            if (dur === null) { setForceError('持续时间必须是有限正数'); return }
                            void handleForce(tag.name, 'hold', undefined, dur)
                          }}
                          className="rounded px-1 py-0.5 text-xs hover:bg-secondary"
                          title="保持当前输出（后端原子捕获）"
                        >
                          H
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const d = prompt('持续时间（秒，留空=永久）：', '')
                            if (d === null) return
                            const dur = parseDuration(d)
                            if (dur === null) { setForceError('持续时间必须是有限正数'); return }
                            void handleForce(tag.name, 'zero', undefined, dur)
                          }}
                          className="rounded px-1 py-0.5 text-xs hover:bg-secondary"
                          title="置零"
                        >
                          0
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const v = prompt('固定值：', '0')
                            if (v === null) return
                            const fv = Number(v)
                            if (!Number.isFinite(fv)) { setForceError('固定值必须是有限数'); return }
                            const d = prompt('持续时间（秒，留空=永久）：', '')
                            if (d === null) return
                            const dur = parseDuration(d)
                            if (dur === null) { setForceError('持续时间必须是有限正数'); return }
                            void handleForce(tag.name, 'fixed', fv, dur)
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
      {forceError ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive" data-testid="force-error">
          强制操作失败：{forceError}
          <button type="button" onClick={() => setForceError(null)} className="ml-2 underline">关闭</button>
        </div>
      ) : null}
    </section>
  )
}
