/**
 * 组态调试首页。
 *
 * 目标界面（设计文档 §一）：
 *   推荐起点：单阀门2阶水箱
 *   [打开 YML]
 *   最近打开 YML
 *     - ...
 *
 * 规则：
 *   - 删除模板区域和模板入口；template/ 目录仍作为打开 YML 的默认目录
 *   - 不提供"新建工程"按钮
 *   - "打开 YML" 文件选择器默认进入 <exe>/template/
 */
import { systemApi } from '../../lib/api'
import { useDslProjectStore } from './useDslProjectStore'
import { realtimeProjectApi } from '../../lib/api'

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

  const openYaml = async () => {
    const path = await realtimeProjectApi.chooseYamlForDsl()
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

  return (
    <div className="flex flex-1 overflow-y-auto bg-background p-8" data-testid="dsl-home">
      <div className="mx-auto w-full max-w-3xl space-y-8">
        <div>
          <h1 className="text-xl font-semibold">组态调试</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            打开或编辑 YML 配置，运行离线仿真、导出与画面绑定。
          </p>
        </div>

        <section className="space-y-3">
          <div className="text-xs text-muted-foreground">推荐起点：单阀门2阶水箱</div>
          <button
            type="button"
            onClick={() => void openYaml()}
            className="flex w-40 items-center justify-center rounded-md border border-border bg-card px-4 py-2 text-xs font-medium hover:bg-secondary"
            data-testid="dsl-open-yaml"
          >
            打开 YML
          </button>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-medium">最近打开 YML</h2>
          {recentPaths.length === 0 ? (
            <p className="text-xs text-muted-foreground" data-testid="dsl-recent-empty">
              暂无最近文件
            </p>
          ) : (
            <ul className="space-y-1" data-testid="dsl-recent-list">
              {recentPaths.map((p) => (
                <li key={p}>
                  <button
                    type="button"
                    onClick={() => void openRecent(p)}
                    className="w-full truncate rounded-md border border-border bg-card px-3 py-2 text-left text-xs hover:bg-secondary"
                    data-testid="dsl-recent-item"
                    data-path={p}
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