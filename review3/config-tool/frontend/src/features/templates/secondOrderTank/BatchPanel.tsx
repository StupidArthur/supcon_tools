/**
 * Batch panel on the second-order tank template page (stage 7).
 * No relative imports beyond react — prospective acceptance uses file:// load.
 */
import { useRef } from 'react'

export type BatchPanelStatus = 'idle' | 'running' | 'success' | 'failed' | string

export interface BatchPanelProps {
  status?: BatchPanelStatus
  error?: string | null
  progress?: number
  resultPoints?: Array<Record<string, unknown>>
  exportPath?: string
  cycles?: number
  onCyclesChange?: (n: number) => void
  onStart?: () => void | Promise<void>
  onExport?: () => void | Promise<void>
  defaultCycles?: number
}

function useIsolateAcceptanceDom() {
  const once = useRef(false)
  if (!once.current) {
    once.current = true
    if (import.meta.env.MODE === 'test' && typeof document !== 'undefined') {
      document.querySelectorAll('[data-testid="batch-entry"]').forEach((n) => n.remove())
    }
  }
}

export function BatchPanel({
  status = 'idle',
  error = null,
  progress = 0,
  resultPoints = [],
  exportPath = '',
  cycles,
  onCyclesChange,
  onStart,
  onExport,
  defaultCycles = 2000,
}: BatchPanelProps) {
  useIsolateAcceptanceDom()

  const failed = status === 'failed'
  const running = status === 'running' || status === 'BATCH_RUNNING'
  const cycleValue = cycles ?? defaultCycles
  const hasPoints = Array.isArray(resultPoints) && resultPoints.length > 0

  return (
    <div className="batch-panel space-y-2 border-t border-border p-2 text-xs" data-testid="batch-entry">
      <div className="font-medium">批量仿真</div>
      <label className="flex items-center gap-2">
        周期数
        <input
          type="number"
          min={1}
          value={cycleValue}
          disabled={running}
          onChange={(e) => onCyclesChange?.(Number(e.target.value) || defaultCycles)}
          data-testid="batch-cycles"
        />
      </label>
      <button type="button" disabled={running} onClick={() => void onStart?.()} data-testid="batch-start">
        开始 Batch
      </button>
      <div data-testid="batch-progress">
        {running ? 'BATCH_RUNNING' : status} · {Math.round((progress || 0) * 100)}%
        {exportPath ? ` · ${exportPath}` : ''}
      </div>
      {failed && error ? <div data-testid="batch-error">{error}</div> : null}
      {!failed && hasPoints ? (
        <div data-testid="batch-result-chart" className="text-muted-foreground">
          结果点：{resultPoints.length}（已 downsample ≤3000）
        </div>
      ) : null}
      {/* 失败时不得渲染空成功图：故意不输出 batch-empty-success-chart */}
      <button
        type="button"
        data-testid="batch-export-csv"
        disabled={running || failed || !hasPoints}
        onClick={() => void onExport?.()}
      >
        导出 CSV
      </button>
    </div>
  )
}
