/**
 * DSL 工程工作区（统一通用布局）。
 *
 * 所有可达 DSL 工程一律渲染：左侧 YAML 源码编辑器 + 可拖动分隔条 + 右侧通用仿真面板。
 * 不再根据 projectKind=template 渲染二阶水箱专用工作区（该 GUI 已暂停，旧代码保留但不引用）。
 *
 * YAML 文本（useDslProjectStore.yamlText）是唯一权威编辑数据：保存 / 另存为 / 离线仿真都用它。
 * 内置模板受保护：无路径或目标为内置模板时强制另存为，禁止覆盖内置模板。
 */
import { useRef, useState } from 'react'
import { systemApi, templateApi } from '../../lib/api'
import { GenericSimPanel } from './GenericSimPanel'
import { useDslProjectStore } from './useDslProjectStore'
import { useGenericSimStore } from './useGenericSimStore'
import { YamlSourceEditor } from './YamlSourceEditor'

const DEFAULT_LEFT_PCT = 38
const MIN_LEFT_PCT = 20
const MAX_LEFT_PCT = 70

interface StatusBadge {
  text: string
  className: string
}

/**
 * 通用 YAML 状态文案（不依赖模板专用 validationErrors）：
 * - 编辑后尚未成功运行：未校验
 * - 最近一次当前草稿仿真成功：最近运行成功
 * - 当前草稿与成功结果 hash 不一致：已修改，需重新运行
 * - 后端解析或运行失败：运行失败
 */
function computeStatusBadge(status: string, owned: boolean, stale: boolean): StatusBadge {
  if (status === 'running' && owned) {
    return { text: '仿真运行中', className: 'bg-blue-50 text-blue-800' }
  }
  if (status === 'failed' && owned) {
    return { text: '运行失败', className: 'bg-red-100 text-red-900' }
  }
  if (status === 'success' && owned) {
    return stale
      ? { text: '已修改，需重新运行', className: 'bg-amber-100 text-amber-900' }
      : { text: '最近运行成功', className: 'bg-emerald-50 text-emerald-800' }
  }
  return { text: '未校验', className: 'bg-muted text-muted-foreground' }
}

export function DslWorkspace() {
  const openHome = useDslProjectStore((s) => s.openHome)
  const projectName = useDslProjectStore((s) => s.projectName)
  const filePath = useDslProjectStore((s) => s.filePath)
  const yamlDirty = useDslProjectStore((s) => s.yamlDirty)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)
  const pushRecent = useDslProjectStore((s) => s.pushRecent)
  const setProjectFile = useDslProjectStore((s) => s.setProjectFile)
  const projectId = useDslProjectStore((s) => s.projectId)

  const simStatus = useGenericSimStore((s) => s.status)
  const simStale = useGenericSimStore((s) => s.stale)
  const boundProjectId = useGenericSimStore((s) => s.boundProjectId)

  const statusBadge = computeStatusBadge(simStatus, boundProjectId === projectId, simStale)

  const handleSave = async () => {
    let path = filePath
    // 无路径（模板副本/新建）或当前就是内置模板：必须另存为，禁止覆盖内置模板。
    if (!path || (await templateApi.isBuiltin(path))) {
      path = await systemApi.saveYAMLFile()
      if (!path) return
      if (await templateApi.isBuiltin(path)) {
        alert('禁止覆盖内置模板，请另存到其他路径')
        return
      }
    }
    const text = useDslProjectStore.getState().yamlText
    await systemApi.writeTextFile(path, text)
    setYamlText(text, false)
    pushRecent(path)
    setProjectFile(path)
  }

  const handleSaveAs = async () => {
    const target = await systemApi.saveYAMLFile()
    if (!target) return
    if (await templateApi.isBuiltin(target)) {
      alert('禁止覆盖内置模板，请另存到其他路径')
      return
    }
    const text = useDslProjectStore.getState().yamlText
    await systemApi.writeTextFile(target, text)
    setYamlText(text, false)
    pushRecent(target)
    setProjectFile(target)
  }

  // 左右分栏的可拖拽分隔条
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT)
  const splitRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)

  const onDividerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onDividerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !splitRef.current) return
    const rect = splitRef.current.getBoundingClientRect()
    if (rect.width <= 0) return
    const pct = ((e.clientX - rect.left) / rect.width) * 100
    setLeftPct(Math.min(MAX_LEFT_PCT, Math.max(MIN_LEFT_PCT, pct)))
  }
  const onDividerUp = () => {
    draggingRef.current = false
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col" data-testid="dsl-workspace">
      <header className="flex flex-wrap items-center gap-2 border-b border-border bg-card px-3 py-2">
        <button
          type="button"
          onClick={openHome}
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary"
          data-testid="dsl-back-home"
        >
          ← 首页
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium" title={filePath || projectName}>
            {projectName || '未命名工程'}
          </div>
          {filePath ? (
            <div className="truncate text-[11px] text-muted-foreground" title={filePath}>
              {filePath}
            </div>
          ) : (
            <div className="truncate text-[11px] text-muted-foreground">未保存</div>
          )}
        </div>
        <span className={`rounded-md px-2 py-0.5 text-xs ${statusBadge.className}`} data-testid="dsl-status-badge">
          {statusBadge.text}
        </span>
        {yamlDirty ? (
          <span className="rounded-md bg-amber-100 px-2 py-0.5 text-xs text-amber-900" data-testid="dsl-dirty-badge">
            未保存
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">已保存</span>
        )}
        <button
          type="button"
          onClick={() => void handleSave()}
          className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
          data-testid="dsl-save"
        >
          保存
        </button>
        <button
          type="button"
          onClick={() => void handleSaveAs()}
          className="rounded-md border border-border px-3 py-1 text-xs"
          data-testid="dsl-save-as"
        >
          另存为
        </button>
      </header>

      <div ref={splitRef} className="flex min-h-0 flex-1 overflow-hidden" data-testid="dsl-split">
        <div style={{ width: `${leftPct}%` }} className="flex min-h-0 flex-col overflow-hidden">
          <YamlSourceEditor />
        </div>
        <div
          onPointerDown={onDividerDown}
          onPointerMove={onDividerMove}
          onPointerUp={onDividerUp}
          onPointerCancel={onDividerUp}
          className="relative w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-primary/60"
          role="separator"
          aria-orientation="vertical"
          data-testid="dsl-split-divider"
        >
          <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <GenericSimPanel />
        </div>
      </div>
    </div>
  )
}
