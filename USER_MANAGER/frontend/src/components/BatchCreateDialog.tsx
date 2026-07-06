import { useState } from 'react'
import { apiClient, type ParseResult, type ParsedRow } from '../lib/api'
import { FixedParamsInfo } from './FixedParamsInfo'

interface Props {
  onStart: (rows: ParsedRow[], concurrency: number) => void
  onClose: () => void
  onMessage?: (msg: string, kind: 'info' | 'success' | 'error') => void
}

export function BatchCreateDialog({ onStart, onClose, onMessage }: Props) {
  const [path, setPath] = useState('')
  const [result, setResult] = useState<ParseResult | null>(null)
  const [concurrency, setConcurrency] = useState(3)
  const [parsing, setParsing] = useState(false)

  async function pickFile() {
    const p = await apiClient.pickExcelFile()
    if (!p) return
    setPath(p)
    setParsing(true)
    try {
      const r = await apiClient.parseExcelFile(p)
      setResult(r)
    } catch (e: any) {
      setResult({
        filename: p,
        users: [],
        errors: [{ row: 0, column: '', msg: String(e) }],
      } as unknown as ParseResult)
    } finally {
      setParsing(false)
    }
  }

  async function downloadTemplate() {
    const p = await apiClient.downloadBatchTemplate()
    if (p && onMessage) {
      onMessage(`模板已保存到 ${p}（含 1 行示例可复制）`, 'success')
    } else if (!p && onMessage) {
      onMessage('已取消保存模板', 'info')
    }
  }

  function start() {
    if (!result) return
    onStart(result.users, concurrency)
  }

  const total = result?.users?.length ?? 0
  const valid = result?.users?.filter((r) => (r.errors?.length ?? 0) === 0).length ?? 0
  const invalid = total - valid
  const fileErrors = result?.errors?.filter((e) => e.row === 0 || e.row === 1) ?? []
  const rowErrors = (result?.users ?? []).flatMap((r) =>
    (r.errors ?? []).map((msg) => ({ row: r.row, msg }))
  )

  return (
    <div className="dialog-backdrop">
      <div className="dialog" style={{ width: 480 }}>
        <h2>批量创建用户</h2>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          <button className="secondary" onClick={pickFile} disabled={parsing}>
            {parsing ? '解析中…' : '选择 xlsx 文件'}
          </button>
          <button className="ghost" onClick={downloadTemplate}>下载模板</button>
          {path && (
            <span style={{ color: 'var(--fg-soft)', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {path.split(/[\\/]/).pop()}
            </span>
          )}
        </div>

        {/* 摘要视图 */}
        {result && (
          <div
            style={{
              padding: '12px 14px',
              background: 'var(--bg-soft)',
              borderRadius: 6,
              marginBottom: 12,
              fontSize: 13,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
              <span>
                共 <strong style={{ fontSize: 16 }}>{total}</strong> 条
              </span>
              <span style={{ color: 'var(--success)' }}>
                ✓ <strong>{valid}</strong> 条可创建
              </span>
              {invalid > 0 && (
                <span style={{ color: 'var(--danger)' }}>
                  ✗ <strong>{invalid}</strong> 条有问题
                </span>
              )}
            </div>

            {/* 文件级错误（缺列等） */}
            {fileErrors.length > 0 && (
              <div className="error-text" style={{ marginTop: 8, fontSize: 12 }}>
                {fileErrors.map((e, i) => (
                  <div key={i}>{e.msg}</div>
                ))}
              </div>
            )}

            {/* 行级错误（折叠显示，最多 5 条，更多可展开） */}
            {rowErrors.length > 0 && (
              <details style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-soft)' }}>
                <summary style={{ cursor: 'pointer', userSelect: 'none' }}>
                  查看 {rowErrors.length} 条行级错误
                </summary>
                <div style={{ marginTop: 4, maxHeight: 160, overflow: 'auto' }}>
                  {rowErrors.map((e, i) => (
                    <div key={i}>
                      行 {e.row}: {e.msg}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}

        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ marginBottom: 0 }}>并发数：</label>
          <input
            type="number"
            min={1}
            max={20}
            value={concurrency}
            onChange={(e) => setConcurrency(Math.max(1, Math.min(20, parseInt(e.target.value) || 3)))}
            style={{ width: 60 }}
          />
          <span style={{ color: 'var(--fg-faint)', fontSize: 12 }}>（1-20）</span>
        </div>

        <FixedParamsInfo variant="block" />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="secondary" onClick={onClose}>取消</button>
          <button
            className="primary"
            onClick={start}
            disabled={!result || valid === 0}
          >
            开始批量创建（{valid} 条）
          </button>
        </div>
      </div>
    </div>
  )
}