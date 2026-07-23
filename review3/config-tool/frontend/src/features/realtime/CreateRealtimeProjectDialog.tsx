import { useState } from 'react'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'

interface Props {
  onClose: () => void
}

export function CreateRealtimeProjectDialog({ onClose }: Props) {
  const createProject = useRealtimeProjectStore((s) => s.createProject)
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!name.trim()) return
    setSubmitting(true)
    await createProject(name.trim())
    setSubmitting(false)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" data-testid="create-project-dialog">
      <div className="w-80 rounded-lg border border-border bg-card p-4 shadow-lg">
        <h3 className="text-sm font-medium">新建实时工程</h3>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void handleSubmit() }}
          placeholder="工程名称"
          autoFocus
          className="mt-3 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          data-testid="create-project-name"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!name.trim() || submitting}
            className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-40"
            data-testid="create-project-confirm"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  )
}
