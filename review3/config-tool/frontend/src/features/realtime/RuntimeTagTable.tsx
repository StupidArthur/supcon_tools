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
  const latestFrame = useRuntimeStore((s) => s.latestFrame)
  const tagCatalog = useRuntimeStore((s) => s.tagCatalog)
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

  // 阶段 D4 收口：位号表的"权威行列表"必须来自 tagCatalog（启动后已加载），
  // 不能从 rawSnapshot 派生。rawSnapshot 在订阅模式下只含当前可见 tag + 元数据，
  // 若以它为行源会产生自我过滤闭环（订阅 → 缩窄 rawSnapshot → 表行消失 → 永不滚动到）。
  // 行值则从 latestFrame.values[tag] / rawSnapshot[tag] 读取，没有时显示 '—'，
  // 绝不能因此把 tag 从表里删掉。
  const numericCatalog = useMemo(() => {
    // 取 numeric tag；再以 validTags（来自 /api/force 校验）做交集，
    // 避免显示后端实际不接受 force / override 的字段。
    const numeric = tagCatalog.filter((t) => t.dataType === 'number').map((t) => t.name)
    if (validTags === null) return numeric
    const set = new Set(validTags)
    return numeric.filter((n) => set.has(n))
  }, [tagCatalog, validTags])

  const tags = useMemo(() => {
    const entries = numericCatalog.map((name) => {
      // 优先 latestFrame（阶段 6 通用 frame，包含全部订阅 tag），其次 rawSnapshot
      let value: unknown = null
      if (latestFrame && Object.prototype.hasOwnProperty.call(latestFrame.values, name)) {
        value = latestFrame.values[name]
      } else if (rawSnapshot && Object.prototype.hasOwnProperty.call(rawSnapshot, name)) {
        value = rawSnapshot[name]
      }
      return { name, value }
    })
    if (!filter) return entries
    const lower = filter.toLowerCase()
    return entries.filter((e) => e.name.toLowerCase().includes(lower))
  }, [numericCatalog, latestFrame, rawSnapshot, filter])

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

  // 阶段 D4 收口：拆成两个 effect。
  // 1) visibleTags 变化时：debounce 后只调用 registerSubscription。
  //    cleanup 仅取消 pending 计时器，不会触发 unregister，避免滚动时
  //    立刻发送一次"无 tagTable"的 subscribe 消息再重发。
  // 2) 仅组件卸载时：unregisterSubscription 一次。
  // 空可见集合显式注册 []（"我订阅空集，server 只回元数据"），不要用 null
  // 让聚合器误把 tagTable 视为"缺席"。
  useEffect(() => {
    const visibleNames = visibleTags.map((v) => v.tag.name).filter((n) => typeof n === 'string')
    const id = setTimeout(() => {
      try {
        registerSubscription('tagTable', visibleNames)
      } catch (e) {
        setForceError(String(e))
      }
    }, SCROLL_SUBSCRIPTION_DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [visibleTags, registerSubscription])

  useEffect(() => {
    return () => unregisterSubscription('tagTable')
  }, [unregisterSubscription])

  // 阶段 D5：force 订阅源。
  // 用户已经设置了 force 的 tag 即使滚出可见区也必须持续订阅，
  // 否则 force UI 显示的运行值会失联。force 集合变化时 debounce 注册。
  const forceTags = useMemo(
    () => Object.keys(forces).filter((k) => typeof k === 'string' && k.length > 0).sort(),
    [forces],
  )
  useEffect(() => {
    const id = setTimeout(() => {
      try {
        registerSubscription('force', forceTags)
      } catch (e) {
        setForceError(String(e))
      }
    }, SCROLL_SUBSCRIPTION_DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [forceTags, registerSubscription])
  useEffect(() => {
    return () => unregisterSubscription('force')
  }, [unregisterSubscription])

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

  // 即便 rawSnapshot 还没有，tagCatalog 也可能已加载；位号表可以基于 catalog 显示。
  // 完全没数据时仍然显示空状态。
  if (tagCatalog.length === 0 && !rawSnapshot) {
    return (
      <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground" data-testid="tag-table-empty">
        未运行。启动实时工程后此处显示位号表。
      </div>
    )
  }

  const getUaValue = (name: string, runtimeValue: unknown): string => {
    const force = forces[name]
    if (!force || force.mode === 'follow') {
      return typeof runtimeValue === 'number' ? runtimeValue.toFixed(4) : '—'
    }
    if (force.mode === 'zero') return '0.0000'
    if (force.mode === 'fixed' || force.mode === 'hold') {
      return typeof force.value === 'number' ? force.value.toFixed(4) : '—'
    }
    return typeof runtimeValue === 'number' ? runtimeValue.toFixed(4) : '—'
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
              data-testid="tag-table-row"
              data-tag-name={tag.name}
              className="absolute grid w-full grid-cols-[2fr_1fr_1fr_1fr_1fr] items-center border-b border-border/50 text-xs"
              style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
            >
              <div className="truncate px-3 font-mono">{tag.name}</div>
              <div className="px-3 text-right font-mono">
                {typeof tag.value === 'number' ? tag.value.toFixed(4) : '—'}
              </div>
              <div className="px-3 text-right font-mono">{getUaValue(tag.name, tag.value)}</div>
              <div className="text-center">
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
                      data-testid="force-clear"
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
