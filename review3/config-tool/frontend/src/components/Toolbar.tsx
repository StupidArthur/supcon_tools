import { useCanvasStore } from '../store/useCanvasStore'
import { configApi, systemApi } from '../lib/api'

export function Toolbar() {
  const view = useCanvasStore((s) => s.view)
  const setView = useCanvasStore((s) => s.setView)
  const clear = useCanvasStore((s) => s.clear)
  const getCanvasState = useCanvasStore((s) => s.getCanvasState)
  const loadCanvasState = useCanvasStore((s) => s.loadCanvasState)
  const nodeCount = useCanvasStore((s) => s.nodes.length)

  const handleExport = async () => {
    try {
      const path = await systemApi.saveYAMLFile()
      if (!path) return
      await configApi.exportYAML(getCanvasState(), path)
      alert('导出成功: ' + path)
    } catch (e) {
      alert('导出失败: ' + String(e))
    }
  }

  const handleImport = async () => {
    try {
      const path = await systemApi.openYAMLFile()
      if (!path) return
      const state = await configApi.importYAML(path)
      loadCanvasState(state)
      alert('导入成功: ' + path)
    } catch (e) {
      alert('导入失败: ' + String(e))
    }
  }

  const handleValidate = async () => {
    try {
      const result = await configApi.validate(getCanvasState())
      if (result.valid) {
        alert('验证通过' + (result.warnings?.length ? '\n警告: ' + result.warnings.join('\n') : ''))
      } else {
        alert('验证失败:\n' + (result.errors?.join('\n') || ''))
      }
    } catch (e) {
      alert('验证失败: ' + String(e))
    }
  }

  return (
    <div className="flex items-center gap-2 border-b border-border bg-card px-4 py-2">
      {/* Tab buttons */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => setView('system')}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            view === 'system'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
        >
          系统管理
        </button>
        <button
          onClick={() => setView('simulation')}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            view === 'simulation'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
        >
          仿真运行
        </button>
        <button
          onClick={() => setView('config')}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            view === 'config'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-secondary'
          }`}
        >
          组态编辑
        </button>
      </div>

      <span className="mx-2 text-sm font-medium">DataFactory</span>

      {/* Config editor buttons (only in config view) */}
      {view === 'config' && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => clear()}
            className="rounded-md border border-border bg-background px-2.5 py-1 text-xs transition-colors hover:bg-secondary"
          >
            新建
          </button>
          <button
            onClick={handleImport}
            className="rounded-md border border-border bg-background px-2.5 py-1 text-xs transition-colors hover:bg-secondary"
          >
            导入YAML
          </button>
          <button
            onClick={handleExport}
            disabled={nodeCount === 0}
            className="rounded-md border border-border bg-background px-2.5 py-1 text-xs transition-colors hover:bg-secondary disabled:opacity-40"
          >
            导出YAML
          </button>
          <button
            onClick={handleValidate}
            disabled={nodeCount === 0}
            className="rounded-md border border-border bg-background px-2.5 py-1 text-xs transition-colors hover:bg-secondary disabled:opacity-40"
          >
            验证
          </button>
        </div>
      )}
    </div>
  )
}
