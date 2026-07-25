import { useState } from 'react'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import type { ProjectView } from './types'

interface Props {
  onClose: () => void
  onCreated?: (proj: ProjectView) => void
}

/**
 * 新建工程对话框（设计文档 §二.3）：
 *   - 只输入工程名称，不弹出目录选择器；
 *   - 自动创建到 <exe>/project/<工程名>/。
 */
export function CreateRealtimeProjectDialog({ onClose, onCreated }: Props) {
  const createProject = useRealtimeProjectStore((s) => s.createProject)
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('工程名称不能为空')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await createProject(trimmed)
      const proj = useRealtimeProjectStore.getState().currentProject
      setSubmitting(false)
      if (proj) {
        onCreated?.(proj)
      } else {
        onClose()
      }
    } catch (e: any) {
      setSubmitting(false)
      setError(String(e))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" data-testid="create-project-dialog">
      <div className="w-80 rounded-lg border border-border bg-card p-4 shadow-lg">
        <h3 className="text-sm font-medium">新建实时工程</h3>
        <p className="mt-1 text-xs text-muted-foreground">工程将创建到默认 project 目录下。</p>
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
        {error ? (
          <div className="mt-2 text-xs text-destructive" data-testid="create-project-error">
            {error}
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1 text-xs hover:bg-secondary"
            data-testid="create-project-cancel"
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