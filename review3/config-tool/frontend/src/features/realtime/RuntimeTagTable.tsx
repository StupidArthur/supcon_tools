import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'

interface ForceEntry {
  mode: string
  value?: number
}

// 阶段 D4：可见区域订阅 debounce。频繁滚动不应每次都发送 WS subscribe 消息。
const SCROLL_SUBSCRIPTION_DEBOUNCE_MS = 100

const ROW_HEIGHT = 28
const VIEWPORT_HEIGHT = 384
const OVERSCAN = 8

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
  const [scrollTop, setScrollTop] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 阶段 D4：useRef 取得稳定的 registerSubscription / unregisterSubscription 引用，
  // 避免 useEffect 每次都重新订阅。
  const registerSubscription = useRuntimeStore((s) => s.registerSubscription)
  const unregisterSubscription = useRuntimeStore((s) => s.unregisterSubscription)

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

  const visibleTags = useMemo(() => {
    const total = tags.length
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
    const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + OVERSCAN * 2
    const end = Math.min(total, start + visibleCount)
    const out: { tag: { name: string; value: unknown }; index: number }[] = []
    for (let i = start; i < end; i++) {
      out.push({ tag: tags[i], index: i })
    }
    return out
  }, [tags, scrollTop])

  // 阶段 D4：滚动 / 过滤变化 → 防抖注册 tag-table 订阅。
  // 关键约束：
  //   - 卸载 / activeDir 切换时必须 unregisterSubscription，避免遗留 source。
  //   - filter 为空 + 无可见 tag 时，传 null（"全量"），让其它 source（趋势 / dashboard）继续生效。
  //   - 防抖：连续滚动只在静止 100ms 后才发一次 registerSubscription 调用。
  useEffect(() => {
    const debounceId = setTimeout(() => {
      const visibleNames = visibleTags.map((v) => v.tag.name).filter((n) => typeof n === 'string')
      // 如果表是空的（无 rawSnapshot / 无 filter match）则传 null（"我不要任何 tag"）
      // 让 computeSubscriptionUnion 在 store 内合并时不会因 tag-table 占一个空数组
      // 而错把 union 锁到 []。
      const payload: string[] | null = visibleNames.length === 0 ? null : visibleNames
      try {
        registerSubscription('tagTable', payload)
      } catch (e) {
        setForceError(String(e))
      }
    }, SCROLL_SUBSCRIPTION_DEBOUNCE_MS)
    return () => {
      clearTimeout(debounceId)
      // 卸载 / deps 变化时主动注销，确保离开该页面后 union 不再包含本 source。
      unregisterSubscription('tagTable')
    }
  }, [visibleTags, registerSubscription, unregisterSubscription])

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
      <div
        ref={scrollRef}
        className="overflow-y-auto rounded-md border border-border"
        style={{ height: VIEWPORT_HEIGHT }}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        data-testid="tag-table-scroll"
      >
        <div className="sticky top-0 z-10 grid grid-cols-[2fr_1fr_1fr_1fr_1fr] border-b border-border bg-card text-xs font-medium">
          <div className="px-3 py-1.5">位号</div>
          <div className="px-3 py-1.5 text-right">运行值</div>
          <div className="px-3 py-1.5 text-right">预计 UA 输出</div>
          <div className="px-3 py-1.5 text-center">强制</div>
          <div className="px-3 py-1.5 text-center">操作</div>
        </div>
        <div style={{ height: tags.length * ROW_HEIGHT, position: 'relative' }}>
          {visibleTags.map(({ tag, index }) => (
            <div
              key={tag.name}
              className="absolute grid w-full grid-cols-[2fr_1fr_1fr_1fr_1fr] items-center border-b border-border/50 text-xs"
              style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
            >
              <div className="truncate px-3 font-mono">{tag.name}</div>
              <div className="px-3 text-right font-mono">
                {typeof tag.value === 'number' ? tag.value.toFixed(4) : String(tag.value ?? '—')}
              </div>
              <div className="px-3 text-right font-mono">{getUaValue(tag.name, tag.value)}</div>
              <div className="px-3 text-center">
                <span className={forces[tag.name] ? 'text-amber-700' : 'text-muted-foreground'}>
                  {getForceLabel(tag.name)}
                </span>
              </div>
              <div className="px-3 text-center">
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
              </div>
            </div>
          ))}
        </div>
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
