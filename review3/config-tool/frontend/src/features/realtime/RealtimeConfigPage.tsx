import { useEffect, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import { CreateRealtimeProjectDialog } from './CreateRealtimeProjectDialog'
import { DuplicateInstancesDialog } from './DuplicateInstancesDialog'
import type { ProjectView } from './types'

export function RealtimeConfigPage() {
  const {
    currentProject,
    currentProjectFile,
    instances,
    duplicates,
    loading,
    error,
    openExistingProject,
    createProjectAt,
    addSource,
    removeSource,
    updateReplicas,
    updateRuntime,
    clearError,
  } = useRealtimeProjectStore()

  const [showCreate, setShowCreate] = useState(false)
  const [cycleTime, setCycleTime] = useState(0.5)
  const [opcUaHost, setOpcUaHost] = useState('0.0.0.0')
  const [opcUaPort, setOpcUaPort] = useState(18951)
  const [runtimeDirty, setRuntimeDirty] = useState(false)

  // 打开工程后，加载持久化的 runtime 默认值
  useEffect(() => {
    if (currentProject?.runtime) {
      setCycleTime(currentProject.runtime.cycleTime || 0.5)
      setOpcUaHost(currentProject.runtime.opcUaHost || '0.0.0.0')
      setOpcUaPort(currentProject.runtime.opcUaPort || 18951)
      setRuntimeDirty(false)
    } else {
      setRuntimeDirty(false)
    }
  }, [currentProject?.id, currentProject?.runtime?.cycleTime, currentProject?.runtime?.opcUaHost, currentProject?.runtime?.opcUaPort])

  const handleReplicasChange = async (sourceId: string, value: string) => {
    if (!currentProject || !currentProjectFile) return
    const n = parseInt(value, 10)
    if (isNaN(n) || n < 1 || n > 100) return
    await updateReplicas(currentProject.id, currentProjectFile, sourceId, n)
  }

  const persistRuntime = async () => {
    if (!currentProject || !currentProjectFile) return
    await updateRuntime(currentProject.id, currentProjectFile, {
      cycleTime,
      opcUaHost,
      opcUaPort,
    })
    setRuntimeDirty(false)
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6" data-testid="realtime-config-page">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-medium">实时工程组态</h2>
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={() => void openExistingProject()}
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
              data-testid="realtime-open-project"
            >
              打开工程
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
              data-testid="realtime-create-project"
            >
              新建工程
            </button>
          </div>
        </div>

        {!currentProject ? (
          <div className="flex flex-col items-center gap-4 rounded-md border border-dashed border-border p-12 text-center" data-testid="realtime-empty-state">
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => void openExistingProject()}
                className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:opacity-90"
                data-testid="realtime-empty-open"
              >
                打开工程
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-secondary"
                data-testid="realtime-empty-create"
              >
                新建工程
              </button>
            </div>
            <div className="text-xs text-muted-foreground">没有打开的工程。新建或打开一个实时工程。</div>
          </div>
        ) : (
          <>
            <section className="rounded-md border border-border bg-card" data-testid="realtime-project-summary">
              <div className="border-b border-border px-3 py-2 text-xs">
                <div className="font-medium">{currentProject.name}</div>
                <div className="mt-1 truncate text-muted-foreground" title={currentProjectFile ?? undefined}>
                  路径：{currentProjectFile}
                </div>
              </div>
            </section>

            <section className="rounded-md border border-border bg-card" data-testid="realtime-sources-table">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">YAML 文件</div>
              <div className="divide-y divide-border">
                {currentProject.sources.length === 0 ? (
                  <div className="px-3 py-3 text-center text-xs text-muted-foreground">尚未添加 YAML</div>
                ) : (
                  currentProject.sources.map((src) => (
                    <div key={src.id} className="flex items-center gap-2 px-3 py-2" data-testid={`realtime-source-row-${src.id}`}>
                      <span className="flex-1 truncate text-xs" title={src.name}>{src.name}</span>
                      <label className="flex items-center gap-1 text-xs">
                        <span className="text-muted-foreground">副本</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={src.replicas}
                          onChange={(e) => void handleReplicasChange(src.id, e.target.value)}
                          className="w-16 rounded border border-border bg-background px-2 py-0.5 text-xs"
                          data-testid={`realtime-replicas-${src.id}`}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => currentProject && currentProjectFile && void removeSource(currentProject.id, currentProjectFile, src.id)}
                        className="text-xs text-muted-foreground hover:text-destructive"
                        data-testid={`realtime-remove-${src.id}`}
                      >
                        移除
                      </button>
                    </div>
                  ))
                )}
              </div>
              <div className="flex items-center justify-between px-3 py-2">
                <button
                  type="button"
                  onClick={() => currentProject && currentProjectFile && void addSource(currentProject.id, currentProjectFile)}
                  disabled={loading}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary disabled:opacity-40"
                  data-testid="realtime-add-source"
                >
                  添加 YAML
                </button>
                <div className="text-xs text-muted-foreground" data-testid="realtime-validation-summary">
                  {(() => {
                    const total = currentProject.sources.reduce((acc, s) => acc + Math.max(1, s.replicas), 0)
                    const passed = duplicates.length === 0
                    return (
                      <>
                        <span>YAML：{currentProject.sources.length} 个</span>
                        <span className="mx-2">展开实例：{total} 个</span>
                        <span>{passed ? '校验通过' : '校验失败'}</span>
                      </>
                    )
                  })()}
                </div>
              </div>
            </section>

            <section className="rounded-md border border-border bg-card" data-testid="realtime-runtime-options">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">运行时默认参数</div>
              <div className="grid grid-cols-3 gap-3 px-3 py-3 text-xs">
                <label className="space-y-1">
                  <span className="text-muted-foreground">控制周期 (秒)</span>
                  <input
                    type="number"
                    min={0.01}
                    step={0.1}
                    value={cycleTime}
                    onChange={(e) => {
                      setCycleTime(Number(e.target.value))
                      setRuntimeDirty(true)
                    }}
                    className="w-full rounded border border-border bg-background px-2 py-1"
                    data-testid="runtime-cycle-time"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground">UA 地址</span>
                  <input
                    value={opcUaHost}
                    onChange={(e) => {
                      setOpcUaHost(e.target.value)
                      setRuntimeDirty(true)
                    }}
                    className="w-full rounded border border-border bg-background px-2 py-1"
                    data-testid="runtime-opc-host"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground">UA 端口</span>
                  <input
                    type="number"
                    value={opcUaPort}
                    onChange={(e) => {
                      setOpcUaPort(Number(e.target.value))
                      setRuntimeDirty(true)
                    }}
                    className="w-full rounded border border-border bg-background px-2 py-1"
                    data-testid="runtime-opc-port"
                  />
                </label>
              </div>
              <div className="flex justify-end px-3 py-2">
                <button
                  type="button"
                  onClick={() => void persistRuntime()}
                  disabled={!runtimeDirty}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary disabled:opacity-40"
                  data-testid="runtime-save"
                >
                  保存到工程
                </button>
              </div>
            </section>
          </>
        )}

        {error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
            <button type="button" onClick={clearError} className="ml-2 underline">关闭</button>
          </div>
        ) : null}

        {loading ? (
          <div className="text-xs text-muted-foreground">处理中...</div>
        ) : null}
      </div>

      {showCreate ? (
        <CreateRealtimeProjectDialog
          onClose={() => setShowCreate(false)}
          onCreated={(proj: ProjectView) => {
            if (proj.runtime) {
              setCycleTime(proj.runtime.cycleTime || 0.5)
              setOpcUaHost(proj.runtime.opcUaHost || '0.0.0.0')
              setOpcUaPort(proj.runtime.opcUaPort || 18951)
            }
            setShowCreate(false)
          }}
        />
      ) : null}

      {duplicates.length > 0 ? (
        <DuplicateInstancesDialog duplicates={duplicates} onClose={clearError} />
      ) : null}
    </div>
  )
}