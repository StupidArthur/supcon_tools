/**
 * 导出对话框：选择文件格式（csv/xlsx/xls）、导出列（默认 YAML display_args）、Excel 工作表名。
 *
 * 纯展示组件：自身不持有业务数据，导出动作通过 onExport 回调交给父组件
 * （父组件负责物化临时 YAML → 重跑引擎 → 调用 ExportBatchFormatted）。
 */
import { useEffect, useState } from 'react'

export type ExportFormat = 'csv' | 'xlsx' | 'xls'

const FORMATS: Array<{ id: ExportFormat; label: string }> = [
  { id: 'csv', label: 'CSV' },
  { id: 'xlsx', label: 'Excel (xlsx)' },
  { id: 'xls', label: 'Excel 97-2003 (xls)' },
]

const DEFAULT_SHEET_NAME = '控制器'

interface ExportDialogProps {
  open: boolean
  /** 可选择的数值列 */
  columns: string[]
  /** 默认勾选的列（来自 YAML display_args） */
  defaultSelected: string[]
  /** 导出将重跑的周期数（仅用于提示） */
  cycles: number
  busy: boolean
  error: string | null
  onClose: () => void
  onExport: (opts: { format: ExportFormat; columns: string[]; sheetName: string }) => void
}

export function ExportDialog(props: ExportDialogProps) {
  const { open, columns, defaultSelected, cycles, busy, error, onClose, onExport } = props
  const [format, setFormat] = useState<ExportFormat>('xlsx')
  const [selected, setSelected] = useState<string[]>(defaultSelected)
  const [sheetName, setSheetName] = useState(DEFAULT_SHEET_NAME)

  useEffect(() => {
    if (open) {
      setFormat('xlsx')
      setSelected(defaultSelected)
      setSheetName(DEFAULT_SHEET_NAME)
    }
  }, [open, defaultSelected])

  if (!open) return null

  const toggle = (col: string) => {
    setSelected((cur) => (cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col]))
  }

  const isExcel = format !== 'csv'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      data-testid="export-dialog"
    >
      <div
        className="flex max-h-[80vh] w-[460px] flex-col rounded-lg bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b border-border px-4 py-3 text-sm font-medium">导出仿真结果</header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3 text-xs">
          <div className="space-y-1.5">
            <div className="text-muted-foreground">文件格式</div>
            <div className="flex gap-1.5">
              {FORMATS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFormat(f.id)}
                  className={`rounded-md border px-3 py-1.5 transition-colors ${
                    format === f.id
                      ? 'border-primary bg-primary/10 font-medium text-primary'
                      : 'border-border hover:bg-secondary'
                  }`}
                  data-testid={`export-format-${f.id}`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {isExcel ? (
            <div className="space-y-1.5">
              <div className="text-muted-foreground">工作表名</div>
              <input
                value={sheetName}
                onChange={(e) => setSheetName(e.target.value)}
                maxLength={31}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5"
                data-testid="export-sheet-name"
              />
            </div>
          ) : null}

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">导出列（默认按 YAML display_args）</span>
              <span className="text-muted-foreground">
                {selected.length}/{columns.length}
              </span>
            </div>
            <div className="max-h-56 space-y-0.5 overflow-y-auto rounded-md border border-border p-2">
              {columns.map((col) => (
                <label
                  key={col}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-secondary/60"
                >
                  <input type="checkbox" checked={selected.includes(col)} onChange={() => toggle(col)} />
                  <span className="font-mono">{col}</span>
                </label>
              ))}
              {columns.length === 0 ? <div className="text-muted-foreground">无可用数值列</div> : null}
            </div>
          </div>

          {error ? (
            <div className="whitespace-pre-wrap break-all text-destructive" data-testid="export-error">
              {error}
            </div>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3 text-xs">
          <span className="mr-auto text-muted-foreground">将重跑 {cycles} 周期生成文件</span>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-border px-3 py-1.5 disabled:opacity-40"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onExport({ format, columns: selected, sheetName })}
            disabled={busy || selected.length === 0}
            className="rounded-md bg-primary px-3 py-1.5 text-primary-foreground disabled:opacity-40"
            data-testid="export-confirm"
          >
            {busy ? '导出中…' : '导出'}
          </button>
        </footer>
      </div>
    </div>
  )
}
