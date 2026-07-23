/**
 * 导出对话框：选择文件格式（csv/xlsx）、导出列（默认 YAML display_args）、Excel 工作表名。
 *
 * 纯展示组件：自身不持有业务数据，导出动作通过 onExport 回调交给父组件。
 * 展示的行数、列、默认选项全部来自传入的 ExportSession 快照（不重新从 Store 取数）；
 * 导出使用会话快照中的内存 rows，按用户基于会话列选择的列导出，不重新仿真。
 *
 * xls 当前版本暂不支持（运行环境缺 xlwt），故不提供该选项。
 */
import { useEffect, useState } from 'react'
import { type ExportFormat } from '../../lib/exportTypes'
import { type ExportSession, sessionNumericColumns } from './exportSession'

const FORMATS: Array<{ id: ExportFormat; label: string }> = [
  { id: 'csv', label: 'CSV' },
  { id: 'xlsx', label: 'Excel (xlsx)' },
]

const DEFAULT_SHEET_NAME = '控制器'

interface ExportDialogProps {
  open: boolean
  /** 打开对话框时冻结的导出会话快照 */
  session: ExportSession | null
  busy: boolean
  error: string | null
  onClose: () => void
  onExport: (opts: { format: ExportFormat; columns: string[]; sheetName: string }) => void
}

export function ExportDialog(props: ExportDialogProps) {
  const { open, session, busy, error, onClose, onExport } = props
  const [format, setFormat] = useState<ExportFormat>('xlsx')
  const [selected, setSelected] = useState<string[]>([])
  const [sheetName, setSheetName] = useState(DEFAULT_SHEET_NAME)

  const numericColumns = session ? sessionNumericColumns(session) : []

  // 每次随会话打开时，用会话快照初始化（默认勾选来自 display_args，过滤到可用数值列）。
  useEffect(() => {
    if (open && session) {
      const avail = sessionNumericColumns(session)
      setFormat('xlsx')
      setSelected(session.selectedColumns.filter((c) => avail.includes(c)))
      setSheetName(DEFAULT_SHEET_NAME)
    }
  }, [open, session])

  if (!open || !session) return null

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
                {selected.length}/{numericColumns.length}
              </span>
            </div>
            <div className="max-h-56 space-y-0.5 overflow-y-auto rounded-md border border-border p-2">
              {numericColumns.map((col) => (
                <label
                  key={col}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-secondary/60"
                >
                  <input type="checkbox" checked={selected.includes(col)} onChange={() => toggle(col)} />
                  <span className="font-mono">{col}</span>
                </label>
              ))}
              {numericColumns.length === 0 ? <div className="text-muted-foreground">无可用数值列</div> : null}
            </div>
          </div>

          {error ? (
            <div className="whitespace-pre-wrap break-all text-destructive" data-testid="export-error">
              {error}
            </div>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3 text-xs">
          <span className="mr-auto text-muted-foreground">导出当前仿真结果：{session.rowCount} 行</span>
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
