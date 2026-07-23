import { useEffect, useState } from 'react'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import { CreateRealtimeProjectDialog } from './CreateRealtimeProjectDialog'
import { DuplicateInstancesDialog } from './DuplicateInstancesDialog'

export function RealtimeConfigPage() {
  const {
    projects,
    currentProject,
    instances,
    duplicates,
    loading,
    error,
    refreshProjects,
    openProject,
    deleteProject,
    addSource,
    removeSource,
    updateReplicas,
    clearError,
  } = useRealtimeProjectStore()

  const [showCreate, setShowCreate] = useState(false)
  const [instanceFilter, setInstanceFilter] = useState('')

  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects])

  const filteredInstances = instanceFilter
    ? instances.filter((i) => i.name.toLowerCase().includes(instanceFilter.toLowerCase()))
    : instances

  const handleReplicasChange = async (sourceId: string, value: string) => {
    if (!currentProject) return
    const n = parseInt(value, 10)
    if (isNaN(n) || n < 1 || n > 100) return
    await updateReplicas(currentProject.id, sourceId, n)
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6" data-testid="realtime-config-page">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-medium">实时工程组态</h2>
          {currentProject ? (
            <span className="text-sm text-muted-foreground">{currentProject.name}</span>
          ) : null}
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="ml-auto rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
            data-testid="realtime-create-project"
          >
            新建工程
          </button>
        </div>

        {projects.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {projects.map((p) => (
              <div key={p.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => void openProject(p.id)}
                  className={`rounded-md border px-3 py-1 text-xs ${
                    currentProject?.id === p.id
                      ? 'border-primary bg-primary/10 font-medium'
                      : 'border-border hover:bg-secondary'
                  }`}
                  data-testid={`realtime-project-${p.id}`}
                >
                  {p.name} ({p.sourceCount})
                </button>
                <button
                  type="button"
                  onClick={() => void deleteProject(p.id)}
                  className="text-xs text-muted-foreground hover:text-destructive"
                  title="删除工程"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ) : null}

        {!currentProject ? (
          <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground" data-testid="realtime-empty-state">
            没有打开的工程。新建或选择一个实时工程开始组态。
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <section className="rounded-md border border-border bg-card" data-testid="realtime-sources-table">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">YAML</div>
              <div className="divide-y divide-border">
                {currentProject.sources.map((src) => (
                  <div key={src.id} className="flex items-center gap-2 px-3 py-2">
                    <span className="flex-1 truncate text-xs" title={src.name}>{src.name}</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={src.replicas}
                      onChange={(e) => void handleReplicasChange(src.id, e.target.value)}
                      className="w-16 rounded border border-border bg-background px-2 py-0.5 text-xs"
                      data-testid={`realtime-replicas-${src.id}`}
                    />
                    <button
                      type="button"
                      onClick={() => currentProject && void removeSource(currentProject.id, src.id)}
                      className="text-xs text-muted-foreground hover:text-destructive"
                      data-testid={`realtime-remove-${src.id}`}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
              <div className="px-3 py-2">
                <button
                  type="button"
                  onClick={() => currentProject && void addSource(currentProject.id)}
                  disabled={loading}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary disabled:opacity-40"
                  data-testid="realtime-add-source"
                >
                  + 添加 YAML
                </button>
              </div>
            </section>

            <section className="rounded-md border border-border bg-card" data-testid="realtime-instances-table">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                <span className="text-xs font-medium">实例</span>
                <span className="text-xs text-muted-foreground">({filteredInstances.length})</span>
                <input
                  type="text"
                  placeholder="搜索..."
                  value={instanceFilter}
                  onChange={(e) => setInstanceFilter(e.target.value)}
                  className="ml-auto w-28 rounded border border-border bg-background px-2 py-0.5 text-xs"
                  data-testid="realtime-instance-filter"
                />
              </div>
              <div className="max-h-80 overflow-y-auto">
                {filteredInstances.length === 0 ? (
                  <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                    {instances.length === 0 ? '暂无实例' : '无匹配结果'}
                  </div>
                ) : (
                  filteredInstances.map((inst, i) => (
                    <div key={`${inst.name}-${i}`} className="px-3 py-1 font-mono text-xs">
                      {inst.name}
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>
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
        <CreateRealtimeProjectDialog onClose={() => setShowCreate(false)} />
      ) : null}

      {duplicates.length > 0 ? (
        <DuplicateInstancesDialog duplicates={duplicates} onClose={clearError} />
      ) : null}
    </div>
  )
}
