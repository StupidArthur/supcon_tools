import type { DuplicateInstance } from './types'

interface Props {
  duplicates: DuplicateInstance[]
  onClose: () => void
}

export function DuplicateInstancesDialog({ duplicates, onClose }: Props) {
  const names = duplicates.map((d) => d.name)

  const handleCopy = () => {
    void navigator.clipboard.writeText(names.join('\n'))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" data-testid="duplicate-dialog">
      <div className="w-96 rounded-lg border border-border bg-card p-4 shadow-lg">
        <h3 className="text-sm font-medium text-destructive">无法完成操作</h3>
        <p className="mt-2 text-xs text-muted-foreground">以下实例名称重复：</p>
        <div className="mt-2 max-h-48 overflow-y-auto rounded-md border border-border bg-background p-2">
          {duplicates.map((dup) => (
            <div key={dup.name} className="mb-2">
              <div className="text-xs font-medium">{dup.name}</div>
              {dup.occurrences.map((occ, i) => (
                <div key={i} className="ml-3 text-xs text-muted-foreground">
                  {occ.sourceFile.split(/[/\\]/).pop()}：{occ.originalName}，副本 {occ.replicaIndex}
                </div>
              ))}
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          请在 DSL 工程中修改实例名称后重新导入。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary"
          >
            复制名称
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
            data-testid="duplicate-dialog-close"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
