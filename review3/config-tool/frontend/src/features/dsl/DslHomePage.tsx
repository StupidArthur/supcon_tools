/**
 * DSL 工程首页：新建 / 打开 / 最近 / 模板
 */
import { systemApi } from '../../lib/api'
import { useTemplateStore } from '../templates/useTemplateStore'
import { useDslProjectStore } from './useDslProjectStore'

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

export function DslHomePage() {
  const openWorkspace = useDslProjectStore((s) => s.openWorkspace)
  const pushRecent = useDslProjectStore((s) => s.pushRecent)
  const recentPaths = useDslProjectStore((s) => s.recentPaths)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)
  const loadBuiltin = useTemplateStore((s) => s.loadBuiltin)
  const loadFromPath = useTemplateStore((s) => s.loadFromPath)
  const reset = useTemplateStore((s) => s.reset)

  const openTemplate = async () => {
    await loadBuiltin()
    const path = useTemplateStore.getState().sourcePath || ''
    openWorkspace({
      editorTab: 'template',
      simTab: 'control',
      projectKind: 'template',
      projectName: '单阀门二阶水箱',
      filePath: path,
    })
  }

  const openYaml = async () => {
    const path = await systemApi.openYAMLFile()
    if (!path) return
    try {
      await loadFromPath(path)
      pushRecent(path)
      openWorkspace({
        editorTab: 'template',
        simTab: 'control',
        projectKind: 'template',
        projectName: basename(path),
        filePath: path,
      })
    } catch {
      try {
        const text = await systemApi.readTextFile(path)
        reset()
        setYamlText(text, false)
        pushRecent(path)
        openWorkspace({
          editorTab: 'yaml',
          simTab: 'control',
          projectKind: 'generic',
          projectName: basename(path),
          filePath: path,
        })
      } catch (err) {
        alert('打开失败: ' + String(err))
      }
    }
  }

  const openRecent = async (path: string) => {
    try {
      await loadFromPath(path)
      pushRecent(path)
      openWorkspace({
        editorTab: 'template',
        projectKind: 'template',
        projectName: basename(path),
        filePath: path,
      })
    } catch {
      try {
        const text = await systemApi.readTextFile(path)
        reset()
        setYamlText(text, false)
        pushRecent(path)
        openWorkspace({
          editorTab: 'yaml',
          projectKind: 'generic',
          projectName: basename(path),
          filePath: path,
        })
      } catch (err) {
        alert('打开失败: ' + String(err))
      }
    }
  }

  const newProject = async () => {
    reset()
    await loadBuiltin()
    const path = useTemplateStore.getState().sourcePath || ''
    openWorkspace({
      editorTab: 'template',
      projectKind: 'template',
      projectName: '单阀门二阶水箱',
      filePath: path,
    })
  }

  return (
    <div className="flex flex-1 overflow-y-auto bg-background p-8" data-testid="dsl-home">
      <div className="mx-auto w-full max-w-3xl space-y-8">
        <div>
          <h1 className="text-xl font-semibold">DSL 工程</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            编辑与调试 DSL、仿真运行、Batch 与导出。实时 OPC UA 请使用「实时运行与 UA」。
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void newProject()}
            className="rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground"
            data-testid="dsl-new-project"
          >
            新建工程
          </button>
          <button
            type="button"
            onClick={() => void openYaml()}
            className="rounded-md border border-border bg-card px-4 py-2 text-xs"
            data-testid="dsl-open-yaml"
          >
            打开 YAML
          </button>
        </div>

        <section className="space-y-2">
          <h2 className="text-sm font-medium">模板</h2>
          <button
            type="button"
            onClick={() => void openTemplate()}
            className="flex w-full items-center justify-between rounded-md border border-border bg-card px-4 py-3 text-left text-xs hover:bg-secondary"
            data-testid="dsl-template-second-order-tank"
          >
            <span className="font-medium">单阀门二阶水箱</span>
            <span className="text-muted-foreground">专用可视化模板</span>
          </button>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-medium">最近工程</h2>
          {recentPaths.length === 0 ? (
            <p className="text-xs text-muted-foreground">暂无最近文件</p>
          ) : (
            <ul className="space-y-1">
              {recentPaths.map((p) => (
                <li key={p}>
                  <button
                    type="button"
                    onClick={() => void openRecent(p)}
                    className="w-full truncate rounded-md border border-border bg-card px-3 py-2 text-left text-xs hover:bg-secondary"
                  >
                    {p}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
