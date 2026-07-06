export interface BatchResult {
  username: string
  nickName: string
  row: number
  success: boolean
  code: string
  msg: string
  error: string
}

interface Props {
  batchId: string | null
  total: number
  done: number
  failed: number
  results: BatchResult[]
  finished: boolean
  onCancel: () => void
  onClose: () => void
  onRefreshList: () => void
}

export function BatchProgressTable({
  total,
  done,
  failed,
  results,
  finished,
  onCancel,
  onClose,
  onRefreshList,
}: Props) {
  const succeeded = results.filter((r) => r.success).length
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <div className="dialog-backdrop">
      <div className="dialog" style={{ minWidth: 720 }}>
        <h2>批量创建进度</h2>

        <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span>
            进度：<strong>{done}</strong> / {total}（{pct}%）
          </span>
          <span className="tag success">{succeeded} 成功</span>
          <span className="tag error">{failed} 失败</span>
        </div>

        <div style={{ background: 'var(--bg-soft)', borderRadius: 6, height: 8, marginBottom: 12, overflow: 'hidden' }}>
          <div
            style={{
              width: `${pct}%`,
              height: '100%',
              background: 'var(--accent)',
              transition: 'width 0.2s',
            }}
          />
        </div>

        {results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>行</th>
                <th>用户名</th>
                <th>昵称</th>
                <th>状态</th>
                <th>消息</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i}>
                  <td>{r.row}</td>
                  <td>{r.username}</td>
                  <td>{r.nickName}</td>
                  <td>
                    {r.success ? (
                      <span className="tag success">成功</span>
                    ) : (
                      <span className="tag error">失败</span>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--fg-soft)' }}>
                    {r.error || r.msg || (r.code && `[${r.code}]`)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          {!finished ? (
            <button className="danger" onClick={onCancel}>取消</button>
          ) : (
            <>
              <button className="secondary" onClick={onClose}>关闭</button>
              <button className="primary" onClick={() => { onRefreshList(); onClose() }}>刷新列表</button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
