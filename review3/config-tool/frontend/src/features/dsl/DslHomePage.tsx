/**
 * DSL 工程首页：新建 / 打开 / 最近 / 模板（二阶水箱为可选示例）
 */
import { systemApi } from '../../lib/api'
import { useTemplateStore } from '../templates/useTemplateStore'
import { useDslProjectStore } from './useDslProjectStore'

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

async function loadYamlAsGeneric(
  path: string,
  opts: {
    reset: () => void
    setYamlText: (t: string, dirty?: boolean) => void
    pushRecent: (p: string) => void
    openWorkspace: (o: Parameters<ReturnType<typeof useDslProjectStore.getState>['openWorkspace']>[0]) => void
  },
) {
  const text = await systemApi.readTextFile(path)
  opts.reset()
  opts.setYamlText(text, false)
  opts.pushRecent(path)
  opts.openWorkspace({
    editorTab: 'yaml',
    simTab: 'run',
    projectKind: 'generic',
    projectName: basename(path),
    filePath: path,
  })
}

export function DslHomePage() {
  const openWorkspace = useDslProjectStore((s) => s.openWorkspace)
  const pushRecent = useDslProjectStore((s) => s.pushRecent)
  const recentPaths = useDslProjectStore((s) => s.recentPaths)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)
  const loadBuiltin = useTemplateStore((s) => s.loadBuiltin)
  const reset = useTemplateStore((s) => s.reset)

  const openTemplate = async () => {
    await loadBuiltin()
    const path = useTemplateStore.getState().sourcePath || ''
    if (path) {
      try {
        const text = await systemApi.readTextFile(path)
        setYamlText(text, false)
      } catch {
        // template UI may still work without yaml buffer
      }
    }
    openWorkspace({
      editorTab: 'template',
      simTab: 'run',
      projectKind: 'template',
      projectName: '单阀门二阶水箱',
      filePath: path,
    })
  }

  const openYaml = async () => {
    const path = await systemApi.openYAMLFile()
    if (!path) return
    try {
      await loadYamlAsGeneric(path, { reset, setYamlText, pushRecent, openWorkspace })
    } catch (err) {
      alert('打开失败: ' + String(err))
    }
  }

  const openRecent = async (path: string) => {
    try {
      await loadYamlAsGeneric(path, { reset, setYamlText, pushRecent, openWorkspace })
    } catch (err) {
      alert('打开失败: ' + String(err))
    }
  }

  const newProject = () => {
    reset()
    setYamlText('', false)
    openWorkspace({
      editorTab: 'yaml',
      simTab: 'run',
      projectKind: 'generic',
      projectName: '未命名工程',
      filePath: '',
    })
  }

  return (
    <div className="flex flex-1 overflow-y-auto bg-background p-8" data-testid="dsl-home">
      <div className="mx-auto w-full max-w-3xl space-y-8">
        <div>
          <h1 className="text-xl font-semibold">DSL 工程</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            编辑 YAML、离线仿真与导出。实时 OPC UA 请使用「实时运行与 UA」。二阶水箱为可选示例模板。
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={newProject}
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
          <h2 className="text-sm font-medium">模板（可选）</h2>
          <button
            type="button"
            onClick={() => void openTemplate()}
            className="flex w-full items-center justify-between rounded-md border border-border bg-card px-4 py-3 text-left text-xs hover:bg-secondary"
            data-testid="dsl-template-second-order-tank"
          >
            <span className="font-medium">单阀门二阶水箱</span>
            <span className="text-muted-foreground">专用可视化（本轮不扩展）</span>
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
