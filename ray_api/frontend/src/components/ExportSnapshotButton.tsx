import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

/**
 * ExportSnapshotButton 导出当前页列表为单页 CSV。
 * 点击后调用后端 ExportSnapshot，文件落到 exe 同级 snapshot/ 目录。
 * filenameBase 形如 "集群名_节点" 或 "全局报警"，后端追加 _{datetime}_snapshot.csv。
 */
export function ExportSnapshotButton({
  filenameBase,
  headers,
  rows,
  disabled,
}: {
  filenameBase: string
  headers: string[]
  rows: string[][]
  disabled?: boolean
}) {
  const [status, setStatus] = useState<'idle' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  const onExport = async () => {
    setStatus('idle')
    setMsg('')
    try {
      const res = await api.exportSnapshot(filenameBase, headers, rows)
      if (res.success) {
        setStatus('done')
        setMsg('已导出: ' + res.path)
      } else {
        setStatus('error')
        setMsg(res.error || '导出失败')
      }
    } catch (e) {
      setStatus('error')
      setMsg(String(e))
    }
    setTimeout(() => {
      setStatus('idle')
      setMsg('')
    }, 5000)
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={onExport} disabled={disabled}>
        导出快照
      </Button>
      {status === 'done' && (
        <span className="truncate text-xs text-green-600" title={msg}>
          {msg}
        </span>
      )}
      {status === 'error' && (
        <span className="truncate text-xs text-red-600" title={msg}>
          {msg}
        </span>
      )}
    </div>
  )
}
