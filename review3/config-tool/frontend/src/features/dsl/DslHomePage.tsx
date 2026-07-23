/**
 * DSL 工程首页。
 *
 * 主流程统一为「模板 → 未保存 YAML 草稿副本 → 文本编辑 → 离线仿真 → 导出 → 保存 → 实时运行」。
 * 模板只是 YAML 初始内容来源：点击模板会读取内置模板原文，创建一个 generic 未保存副本，
 * 进入通用左右分栏工作区；不再进入二阶水箱专用 GUI，也不把内置模板路径加入最近工程。
 *
 * 首页顺序：模板（推荐起点） / 打开 YAML / 新建空白工程 / 最近工程。
 */
import { systemApi, templateApi } from '../../lib/api'
import { useDslProjectStore } from './useDslProjectStore'

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

async function loadYamlAsGeneric(
  path: string,
  opts: {
    setYamlText: (t: string, dirty?: boolean) => void
    pushRecent: (p: string) => void
    openWorkspace: (o: Parameters<ReturnType<typeof useDslProjectStore.getState>['openWorkspace']>[0]) => void
  },
) {
  const text = await systemApi.readTextFile(path)
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

  // 模板 → 未保存的 generic YAML 草稿副本（filePath=''，yamlDirty=true）。
  // 第一次保存必须另存为；禁止加入最近工程；不进入专用 GUI。
  const openTemplate = async () => {
    try {
      const doc = await templateApi.loadBuiltin()
      const path = (doc as any)?.path || ''
      if (!path) {
        alert('无法定位内置模板路径')
        return
      }
      const text = await systemApi.readTextFile(path)
      openWorkspace({
        editorTab: 'yaml',
        simTab: 'run',
        projectKind: 'generic',
        projectName: '单阀门二阶水箱（模板副本）',
        filePath: '',
      })
      setYamlText(text, true)
    } catch (err) {
      alert('打开模板失败: ' + String(err))
    }
  }

  const openYaml = async () => {
    const path = await systemApi.openYAMLFile()
    if (!path) return
    try {
      await loadYamlAsGeneric(path, { setYamlText, pushRecent, openWorkspace })
    } catch (err) {
      alert('打开失败: ' + String(err))
    }
  }

  const openRecent = async (path: string) => {
    try {
      await loadYamlAsGeneric(path, { setYamlText, pushRecent, openWorkspace })
    } catch (err) {
      alert('打开失败: ' + String(err))
    }
  }

  const newProject = () => {
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
            编辑 YAML、离线仿真与导出。实时 OPC UA 请使用「实时运行与 UA」。模板是推荐起点，进入后为通用 YAML 文本工作流。
          </p>
        </div>

        <section className="space-y-2">
          <h2 className="text-sm font-medium">模板（推荐起点）</h2>
          <button
            type="button"
            onClick={() => void openTemplate()}
            className="flex w-full items-center justify-between rounded-md border border-border bg-card px-4 py-3 text-left text-xs hover:bg-secondary"
            data-testid="dsl-template-second-order-tank"
          >
            <span className="font-medium">单阀门二阶水箱</span>
            <span className="text-muted-foreground">生成未保存 YAML 副本后可编辑</span>
          </button>
        </section>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void openYaml()}
            className="rounded-md border border-border bg-card px-4 py-2 text-xs"
            data-testid="dsl-open-yaml"
          >
            打开 YAML
          </button>
          <button
            type="button"
            onClick={newProject}
            className="rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground"
            data-testid="dsl-new-project"
          >
            新建空白工程
          </button>
        </div>

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
