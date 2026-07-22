/**
 * DSL 工程工作区：模板 / YAML / 拓扑 + 仿真区
 */
import { useEffect } from 'react'
import { systemApi, templateApi } from '../../lib/api'
import type { DslEditorTab } from '../app/navigation'
import { SecondOrderTankPage } from '../templates/secondOrderTank/SecondOrderTankPage'
import { useTemplateStore } from '../templates/useTemplateStore'
import { SimWorkspace } from './SimWorkspace'
import { TopologyDiagnosticsPanel } from './TopologyDiagnosticsPanel'
import { useDslProjectStore } from './useDslProjectStore'
import { YamlSourceEditor } from './YamlSourceEditor'

const EDITOR_TABS: Array<{ id: DslEditorTab; label: string }> = [
  { id: 'template', label: '模板视图' },
  { id: 'yaml', label: 'YAML 源码' },
  { id: 'topology', label: '拓扑与诊断' },
]

export function DslWorkspace() {
  const editorTab = useDslProjectStore((s) => s.editorTab)
  const setEditorTab = useDslProjectStore((s) => s.setEditorTab)
  const projectKind = useDslProjectStore((s) => s.projectKind)
  const projectName = useDslProjectStore((s) => s.projectName)
  const filePath = useDslProjectStore((s) => s.filePath)
  const yamlDirty = useDslProjectStore((s) => s.yamlDirty)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)
  const openHome = useDslProjectStore((s) => s.openHome)
  const pushRecent = useDslProjectStore((s) => s.pushRecent)
  const setProjectFile = useDslProjectStore((s) => s.setProjectFile)

  const dirtyPaths = useTemplateStore((s) => s.dirtyPaths)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const sourcePath = useTemplateStore((s) => s.sourcePath)
  const save = useTemplateStore((s) => s.save)

  const isDirty = projectKind === 'generic' ? yamlDirty : dirtyPaths.size > 0 || yamlDirty
  // Generic YAML: do not block save/workspace on tank template validation rules.
  const hasErrors = projectKind === 'template' && validationErrors.length > 0

  // Sync YAML buffer when entering YAML tab for template projects.
  useEffect(() => {
    if (editorTab !== 'yaml') return
    if (projectKind !== 'template') return
    const path = sourcePath || filePath
    if (!path) return
    let cancelled = false
    systemApi
      .readTextFile(path)
      .then((text) => {
        if (!cancelled) setYamlText(text, false)
      })
      .catch((err) => console.warn('load yaml text:', err))
    return () => {
      cancelled = true
    }
  }, [editorTab, projectKind, sourcePath, filePath, setYamlText])

  const handleSave = async () => {
    if (hasErrors) return
    if (projectKind === 'template') {
      if (sourcePath && (await templateApi.isBuiltin(sourcePath))) {
        await handleSaveAs()
        return
      }
      await save()
      return
    }
    // generic: require Save As path if no file
    const path = filePath || (await systemApi.saveYAMLFile())
    if (!path) return
    const text = useDslProjectStore.getState().yamlText
    // Write via temp materialize then... we need WriteTextFile - use WriteTemp + user save dialog content
    // Minimal: SaveYAMLFile dialog then WriteTempYAML isn't enough. Add write via allocate+copy?
    // Use WriteTempYAML pattern: write content by SaveTemplate isn't applicable.
    // Fallback: write using WriteTempYAML then tell user - better add WriteTextFile.
    await writeTextFile(path, text)
    setYamlText(text, false)
    pushRecent(path)
    setProjectFile(path)
  }

  const handleSaveAs = async () => {
    if (hasErrors) return
    const target = await systemApi.saveYAMLFile()
    if (!target) return
    if (projectKind === 'template') {
      await save({ targetPath: target, allowOverwrite: true })
      pushRecent(target)
      setProjectFile(target)
      return
    }
    const text = useDslProjectStore.getState().yamlText
    await writeTextFile(target, text)
    setYamlText(text, false)
    pushRecent(target)
    setProjectFile(target)
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
          ) : null}
        </div>
        <span
          className={`rounded-md px-2 py-0.5 text-xs ${
            hasErrors ? 'bg-red-100 text-red-900' : 'bg-emerald-50 text-emerald-800'
          }`}
          data-testid="dsl-validation-badge"
        >
          {hasErrors ? `校验失败 ${validationErrors.length}` : '校验通过'}
        </span>
        {isDirty ? (
          <span className="rounded-md bg-amber-100 px-2 py-0.5 text-xs text-amber-900" data-testid="dsl-dirty-badge">
            未保存
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">已保存</span>
        )}
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={hasErrors || (!isDirty && projectKind === 'template')}
          className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-40"
          data-testid="dsl-save"
        >
          保存
        </button>
        <button
          type="button"
          onClick={() => void handleSaveAs()}
          disabled={hasErrors}
          className="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-40"
          data-testid="dsl-save-as"
        >
          另存为
        </button>
      </header>

      <div className="flex items-center gap-1 border-b border-border px-2 py-1">
        {EDITOR_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setEditorTab(t.id)}
            className={`rounded-md px-2.5 py-1 text-xs ${
              editorTab === t.id
                ? 'bg-secondary font-medium'
                : 'text-muted-foreground hover:bg-secondary/60'
            }`}
            data-testid={`dsl-editor-tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-[3] overflow-hidden">
          {editorTab === 'template' ? (
            projectKind === 'template' ? (
              <SecondOrderTankPage embedded />
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-xs text-muted-foreground" data-testid="no-template-view">
                当前 DSL 没有专用可视化模板，请使用 YAML 源码。
              </div>
            )
          ) : null}
          {editorTab === 'yaml' ? <YamlSourceEditor /> : null}
          {editorTab === 'topology' ? <TopologyDiagnosticsPanel /> : null}
        </div>
        <div className="min-h-[220px] flex-[2] overflow-hidden">
          <SimWorkspace />
        </div>
      </div>
    </div>
  )
}

async function writeTextFile(path: string, content: string): Promise<void> {
  await systemApi.writeTextFile(path, content)
}
