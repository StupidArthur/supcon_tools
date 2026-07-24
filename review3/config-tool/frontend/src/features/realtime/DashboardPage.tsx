import { useCallback, useEffect, useMemo, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'
import type { Dashboard, DashboardWidget, DashboardWidgetType } from './types'

interface Props {
  projectId: string
}

const WIDGET_TYPES: DashboardWidgetType[] = ['value', 'gauge', 'lamp', 'trend', 'write', 'alarm-list', 'text']

function newId(): string {
  return `w_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

function emptyDashboard(): Dashboard {
  return { version: 1, pages: [{ id: 'main', name: '主画面', widgets: [] }] }
}

export function DashboardPage({ projectId }: Props) {
  const latestFrame = useRuntimeStore((s) => s.latestFrame)
  const stale = useRuntimeStore((s) => s.stale)
  const connectionState = useRuntimeStore((s) => s.connectionState)
  const session = useRealtimeRunSessionStore((s) => s.session)

  const [dashboard, setDashboard] = useState<Dashboard>(emptyDashboard())
  const [activePageId, setActivePageId] = useState('main')
  const [editMode, setEditMode] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await realtimeProjectApi.getDashboard(projectId) as any
      const dash = d && d.pages ? d : emptyDashboard()
      setDashboard(dash)
      if (dash.pages.length > 0) setActivePageId(dash.pages[0].id)
    } catch (e: any) {
      setError(String(e))
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const save = useCallback(async (d: Dashboard) => {
    setError(null)
    try {
      const saved = await realtimeProjectApi.saveDashboard(projectId, d) as any
      setDashboard(saved)
    } catch (e: any) {
      setError(String(e))
    }
  }, [projectId])

  const activePage = useMemo(
    () => dashboard.pages.find((p) => p.id === activePageId) || dashboard.pages[0],
    [dashboard, activePageId],
  )

  // 阶段 D5：dashboard 订阅源。当前 activePage 上所有 widget 的 tag 集合
  // 都应当持续订阅，避免用户把 trend widget 滚出可见区或切换到其它 page
  // 后无法恢复运行值。卸载 / 切 project 时注销。
  const registerSubscription = useRuntimeStore((s) => s.registerSubscription)
  const unregisterSubscription = useRuntimeStore((s) => s.unregisterSubscription)

  const dashboardTags = useMemo(() => {
    if (!activePage) return []
    const set = new Set<string>()
    for (const w of activePage.widgets) {
      if (w.tag && typeof w.tag === 'string') set.add(w.tag)
    }
    return Array.from(set).sort()
  }, [activePage])

  // 阶段 5-7：项目身份校验。session 可能属于另一个项目，
  // 此时 dashboard 的 tag 订阅来自当前项目，与 session 的 tag 不匹配。
  const sessionProjectMismatch = !!session && !!session.projectId && session.projectId !== projectId

  useEffect(() => {
    // 阶段 5-7：session 与当前 dashboard 项目不匹配时，不注册订阅
    // （tag 属于另一个项目，订阅无意义）
    if (sessionProjectMismatch) {
      unregisterSubscription('dashboard')
      return () => unregisterSubscription('dashboard')
    }
    if (dashboardTags.length === 0) {
      // 没有 dashboard tag → 显式 [] 表达"我订阅空集，server 只回元数据"
      registerSubscription('dashboard', [])
      return () => unregisterSubscription('dashboard')
    }
    try {
      registerSubscription('dashboard', dashboardTags)
    } catch (e) {
      setError(String(e))
    }
    return () => unregisterSubscription('dashboard')
  }, [dashboardTags, registerSubscription, unregisterSubscription, sessionProjectMismatch])

  const updateWidget = (widgetId: string, patch: Partial<DashboardWidget>) => {
    setDashboard((prev) => ({
      ...prev,
      pages: prev.pages.map((p) =>
        p.id === activePage.id
          ? { ...p, widgets: p.widgets.map((w) => (w.id === widgetId ? { ...w, ...patch } : w)) }
          : p,
      ),
    }))
  }

  const addWidget = (type: DashboardWidgetType) => {
    const w: DashboardWidget = { id: newId(), type, tag: '', x: 0, y: 0, w: 3, h: 2, options: {} }
    setDashboard((prev) => ({
      ...prev,
      pages: prev.pages.map((p) => (p.id === activePage.id ? { ...p, widgets: [...p.widgets, w] } : p)),
    }))
    setSelectedWidget(w.id)
  }

  const removeWidget = (widgetId: string) => {
    setDashboard((prev) => ({
      ...prev,
      pages: prev.pages.map((p) =>
        p.id === activePage.id ? { ...p, widgets: p.widgets.filter((w) => w.id !== widgetId) } : p,
      ),
    }))
  }

  const addPage = () => {
    const id = newId()
    setDashboard((prev) => ({ ...prev, pages: [...prev.pages, { id, name: `画面${prev.pages.length + 1}`, widgets: [] }] }))
    setActivePageId(id)
  }

  const removePage = (pageId: string) => {
    setDashboard((prev) => {
      const pages = prev.pages.filter((p) => p.id !== pageId)
      return { ...prev, pages: pages.length ? pages : [{ id: 'main', name: '主画面', widgets: [] }] }
    })
  }

  const valueOf = (tag: string): number | null => {
    if (!latestFrame || !tag) return null
    const v = latestFrame.values[tag]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }

  const statusBadge = () => {
    if (!session) return <span className="text-muted-foreground">未运行</span>
    if (connectionState === 'disconnected') return <span className="text-amber-700">连接断开</span>
    if (stale) return <span className="text-amber-700">数据过期</span>
    return <span className="text-green-700">实时</span>
  }

  const selected = activePage?.widgets.find((w) => w.id === selectedWidget) || null
  const canEdit = editMode && !sessionProjectMismatch

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6" data-testid="dashboard-page">
      <div className="mx-auto max-w-5xl space-y-3">
        {sessionProjectMismatch ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-xs text-amber-700">
            当前运行的会话属于项目 {session?.projectName || session?.projectId}，与画面所属项目不匹配。切换到该项目后可编辑画面。
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">画面</span>
          {statusBadge()}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => { if (!sessionProjectMismatch) setEditMode((v) => !v) }}
              disabled={sessionProjectMismatch}
              className={`rounded border border-border px-2 py-1 text-xs ${sessionProjectMismatch ? 'cursor-not-allowed opacity-50' : 'hover:bg-secondary'}`}
              data-testid="dashboard-edit-toggle"
            >
              {editMode ? '运行模式' : '编辑模式'}
            </button>
            <button
              type="button"
              onClick={() => { if (canEdit) void save(dashboard) }}
              disabled={!canEdit}
              className={`rounded px-2 py-1 text-xs ${canEdit ? 'bg-primary text-primary-foreground' : 'cursor-not-allowed bg-muted text-muted-foreground'}`}
              data-testid="dashboard-save"
            >
              保存
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1">
          {dashboard.pages.map((p) => (
            <div key={p.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setActivePageId(p.id)}
                className={`rounded border px-2 py-0.5 text-xs ${p.id === activePageId ? 'border-primary bg-primary/10' : 'border-border'}`}
              >
                {p.name}
              </button>
              {editMode ? (
                <button type="button" onClick={() => removePage(p.id)} className="text-xs text-muted-foreground hover:text-destructive">×</button>
              ) : null}
            </div>
          ))}
          {editMode ? (
            <button type="button" onClick={addPage} className="rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary">+ 页面</button>
          ) : null}
        </div>

        {editMode ? (
          <div className="flex flex-wrap gap-1">
            {WIDGET_TYPES.map((t) => (
              <button key={t} type="button" onClick={() => addWidget(t)} className="rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary">
                + {t}
              </button>
            ))}
          </div>
        ) : null}

        <div className="grid grid-cols-12 gap-2" data-testid="dashboard-grid">
          {activePage?.widgets.map((w) => (
            <div
              key={w.id}
              className={`rounded-md border p-2 ${selectedWidget === w.id ? 'border-primary' : 'border-border'}`}
              style={{ gridColumn: `span ${Math.min(12, Math.max(1, w.w))}`, gridRow: `span ${Math.max(1, w.h)}` }}
              onClick={() => editMode && setSelectedWidget(w.id)}
              data-testid={`widget-${w.id}`}
            >
              <WidgetView widget={w} value={valueOf(w.tag)} stale={stale} connected={connectionState === 'connected'} missing={!!w.tag && valueOf(w.tag) === null} />
              {editMode ? (
                <div className="mt-1 flex items-center gap-1 text-xs">
                  <button type="button" onClick={() => removeWidget(w.id)} className="text-muted-foreground hover:text-destructive">删除</button>
                </div>
              ) : null}
            </div>
          ))}
          {activePage?.widgets.length === 0 ? (
            <div className="col-span-12 rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              空画面。{editMode ? '点击上方按钮添加组件。' : '进入编辑模式添加组件。'}
            </div>
          ) : null}
        </div>

        {editMode && selected ? (
          <WidgetEditor
            widget={selected}
            onChange={(patch) => updateWidget(selected.id, patch)}
          />
        ) : null}

        {error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">{error}</div>
        ) : null}
      </div>
    </div>
  )
}

function WidgetView({ widget, value, stale, connected, missing }: {
  widget: DashboardWidget
  value: number | null
  stale: boolean
  connected: boolean
  missing: boolean
}) {
  const title = widget.options?.title || widget.tag || widget.type
  const unit = widget.options?.unit || ''
  const decimals = typeof widget.options?.decimals === 'number' ? widget.options.decimals : 3

  const stateHint = !connected ? '连接断开' : stale ? '数据过期' : missing ? '位号缺失' : ''

  if (widget.type === 'text') {
    return <div className="text-xs">{String(widget.options?.text || title)}</div>
  }

  if (widget.type === 'lamp') {
    const threshold = Number(widget.options?.threshold ?? 0)
    const on = value != null && value >= threshold
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className={`inline-block h-3 w-3 rounded-full ${on ? 'bg-red-500' : 'bg-green-500'}`} />
        <span>{title}</span>
        <span className="text-muted-foreground">{on ? 'ON' : 'OFF'}</span>
      </div>
    )
  }

  if (widget.type === 'gauge') {
    const min = Number(widget.options?.min ?? 0)
    const max = Number(widget.options?.max ?? 1)
    const pct = value != null ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0
    return (
      <div className="space-y-1 text-xs">
        <div className="flex justify-between"><span>{title}</span><span>{value != null ? value.toFixed(decimals) : '—'}{unit}</span></div>
        <div className="h-2 w-full rounded bg-secondary"><div className="h-2 rounded bg-primary" style={{ width: `${pct}%` }} /></div>
        {stateHint ? <div className="text-amber-700">{stateHint}</div> : null}
      </div>
    )
  }

  // value / trend / write / alarm-list 简化为数值显示
  return (
    <div className="space-y-0.5 text-xs">
      <div className="text-muted-foreground">{title}</div>
      <div className="font-mono text-base">{value != null ? value.toFixed(decimals) : '—'}{unit}</div>
      {stateHint ? <div className="text-amber-700">{stateHint}</div> : null}
    </div>
  )
}

function WidgetEditor({ widget, onChange }: { widget: DashboardWidget; onChange: (patch: Partial<DashboardWidget>) => void }) {
  return (
    <div className="space-y-2 rounded-md border border-border p-3" data-testid="widget-editor">
      <div className="text-xs font-medium">编辑组件：{widget.type}</div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <label className="space-y-0.5">
          <span className="text-muted-foreground">位号</span>
          <input value={widget.tag} onChange={(e) => onChange({ tag: e.target.value })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
        <label className="space-y-0.5">
          <span className="text-muted-foreground">标题</span>
          <input value={widget.options?.title || ''} onChange={(e) => onChange({ options: { ...widget.options, title: e.target.value } })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
        <label className="space-y-0.5">
          <span className="text-muted-foreground">单位</span>
          <input value={widget.options?.unit || ''} onChange={(e) => onChange({ options: { ...widget.options, unit: e.target.value } })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
        <label className="space-y-0.5">
          <span className="text-muted-foreground">宽</span>
          <input type="number" value={widget.w} onChange={(e) => onChange({ w: Number(e.target.value) })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
        <label className="space-y-0.5">
          <span className="text-muted-foreground">高</span>
          <input type="number" value={widget.h} onChange={(e) => onChange({ h: Number(e.target.value) })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
        <label className="space-y-0.5">
          <span className="text-muted-foreground">小数位</span>
          <input type="number" value={widget.options?.decimals ?? 3} onChange={(e) => onChange({ options: { ...widget.options, decimals: Number(e.target.value) } })} className="block w-full rounded border border-border bg-background px-2 py-0.5" />
        </label>
      </div>
    </div>
  )
}
