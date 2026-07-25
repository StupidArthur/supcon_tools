import type { ExpandedInstance, RealtimeSource } from './types'

interface Props {
  instances: ExpandedInstance[]
  sources: RealtimeSource[]
  onSelect: (instanceName: string) => void
}

export function RuntimeInstanceTable({ instances, sources, onSelect }: Props) {
  if (instances.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground" data-testid="runtime-instance-table-empty">
        当前工程没有展开实例。
      </div>
    )
  }

  // source_id -> source name
  const sourceNameById = new Map<string, string>()
  for (const s of sources) sourceNameById.set(s.id, s.name)

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="runtime-instance-table">
      <div className="grid grid-cols-[2fr_2fr_1fr] border-b border-border bg-card text-xs font-medium">
        <div className="px-3 py-1.5">实例名</div>
        <div className="px-3 py-1.5">画面模板</div>
        <div className="px-3 py-1.5 text-center">详情</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {instances.map((inst, i) => (
          <div
            key={`${inst.name}-${i}`}
            className="grid grid-cols-[2fr_2fr_1fr] border-b border-border/50 text-xs"
            data-testid={`runtime-instance-row-${inst.name}`}
            data-instance-name={inst.name}
          >
            <div className="truncate px-3 py-1.5 font-mono">{inst.name}</div>
            <div className="truncate px-3 py-1.5 text-muted-foreground" title={sourceNameById.get(inst.sourceId) || inst.sourceId}>
              {sourceNameById.get(inst.sourceId) || inst.sourceId}
            </div>
            <div className="px-3 py-1.5 text-center">
              <button
                type="button"
                onClick={() => onSelect(inst.name)}
                className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-secondary"
                data-testid={`runtime-instance-detail-${inst.name}`}
              >
                详情
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}