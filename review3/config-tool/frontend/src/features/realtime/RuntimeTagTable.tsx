import { useMemo, useState } from 'react'
import { useRuntimeStore } from '../runtime/useRuntimeStore'

export function RuntimeTagTable() {
  const rawSnapshot = useRuntimeStore((s) => s.rawSnapshot)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const stale = useRuntimeStore((s) => s.stale)
  const [filter, setFilter] = useState('')

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

  if (!rawSnapshot) {
    return (
      <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground" data-testid="tag-table-empty">
        未运行。启动实时工程后此处显示位号表。
      </div>
    )
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
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => (
              <tr key={tag.name} className="border-b border-border/50">
                <td className="px-3 py-1 font-mono">{tag.name}</td>
                <td className="px-3 py-1 text-right font-mono">
                  {typeof tag.value === 'number' ? tag.value.toFixed(4) : String(tag.value ?? '—')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
