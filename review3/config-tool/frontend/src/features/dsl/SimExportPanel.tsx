/**
 * Export the current offline simulation result as CSV (no re-run).
 */
import { useState } from 'react'
import { systemApi } from '../../lib/api'
import { useGenericSimStore } from './useGenericSimStore'

export function SimExportPanel() {
  const status = useGenericSimStore((s) => s.status)
  const columns = useGenericSimStore((s) => s.columns)
  const rows = useGenericSimStore((s) => s.rows)
  const hasResult = status === 'success' && rows.length > 0

  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleExport = async () => {
    setMessage(null)
    setError(null)
    if (!hasResult) {
      setError('未运行成功，禁止导出')
      return
    }
    setBusy(true)
    try {
      const path = await systemApi.saveCSVFile()
      if (!path) {
        setBusy(false)
        return
      }
      await systemApi.exportCSVRows(columns, rows as Array<Record<string, any>>, path)
      setMessage('已导出: ' + path)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 p-3 text-xs" data-testid="sim-export-panel">
      <div className="font-medium">导出</div>
      <p className="text-muted-foreground">
        导出当前这次仿真结果为 CSV，与结果趋势使用同一份数据，不会重新运行仿真。
      </p>
      <div>
        {hasResult ? `当前结果：${rows.length} 行 · ${columns.length} 列` : '尚无可用结果'}
      </div>
      <button
        type="button"
        onClick={() => void handleExport()}
        disabled={!hasResult || busy}
        className="rounded-md border border-border bg-card px-3 py-1.5 hover:bg-secondary disabled:opacity-40"
        data-testid="sim-export-button"
      >
        {busy ? '导出中…' : '导出 CSV'}
      </button>
      {message ? <div className="text-emerald-700">{message}</div> : null}
      {error ? (
        <div className="text-destructive" data-testid="sim-export-error">
          {error}
        </div>
      ) : null}
    </div>
  )
}
