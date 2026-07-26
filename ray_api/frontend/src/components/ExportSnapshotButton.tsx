import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

/**
 * ExportSnapshotButton 导出当前页列表为单页 CSV。
 * 点击后调用后端 ExportSnapshot，文件落到 exe 同级 snapshot/ 目录。
 * filenameBase 形如 "集群名_节点" 或 "全局报警"，后端追加 _{datetime}_snapshot.csv。
 * withPush=true 时，附加渲染"导出并推送"按钮（走 ExportSnapshotAndPush，结果同时显示两条反馈）。
 */
export function ExportSnapshotButton({
  filenameBase,
  headers,
  rows,
  withPush = false,
  disabled,
}: {
  filenameBase: string
  headers: string[]
  rows: string[][]
  withPush?: boolean
  disabled?: boolean
}) {
  const [exportStatus, setExportStatus] = useState<{ kind: 'idle' | 'done' | 'error'; msg: string }>({
    kind: 'idle',
    msg: '',
  })
  const [pushStatus, setPushStatus] = useState<{ kind: 'idle' | 'done' | 'error'; msg: string }>({
    kind: 'idle',
    msg: '',
  })

  const clearTimers: number[] = []

  const onExport = async () => {
    setExportStatus({ kind: 'idle', msg: '' })
    setPushStatus({ kind: 'idle', msg: '' })
    try {
      const res = await api.exportSnapshot(filenameBase, headers, rows)
      if (res.success) {
        setExportStatus({ kind: 'done', msg: '已导出: ' + res.path })
      } else {
        setExportStatus({ kind: 'error', msg: res.error || '导出失败' })
      }
    } catch (e) {
      setExportStatus({ kind: 'error', msg: String(e) })
    }
    setTimeout(() => setExportStatus((s) => (s.kind === 'idle' ? s : { kind: 'idle', msg: '' })), 5000)
  }

  const onExportAndPush = async () => {
    setExportStatus({ kind: 'idle', msg: '' })
    setPushStatus({ kind: 'idle', msg: '' })
    try {
      const res = await api.exportSnapshotAndPush(filenameBase, headers, rows)
      // 导出始终会写本地（哪怕推送失败），用 path 区分两条反馈
      if (res.path) {
        setExportStatus({
          kind: res.error ? 'error' : 'done',
          msg: res.error ? `导出失败: ${res.error}` : '已导出: ' + res.path,
        })
      }
      if (res.success) {
        setPushStatus({ kind: 'done', msg: '已推送' })
      } else if (res.pushError) {
        setPushStatus({ kind: 'error', msg: '推送失败: ' + res.pushError })
      } else if (!res.error) {
        setPushStatus({ kind: 'error', msg: '未知推送失败' })
      }
    } catch (e) {
      setExportStatus({ kind: 'done', msg: '本地已导出' })
      setPushStatus({ kind: 'error', msg: String(e) })
    }
    setTimeout(
      () => setExportStatus((s) => (s.kind === 'idle' ? s : { kind: 'idle', msg: '' })),
      5000,
    )
    setTimeout(
      () => setPushStatus((s) => (s.kind === 'idle' ? s : { kind: 'idle', msg: '' })),
      5000,
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={onExport} disabled={disabled}>
        导出快照
      </Button>
      {withPush && (
        <Button variant="outline" size="sm" onClick={onExportAndPush} disabled={disabled}>
          导出并推送
        </Button>
      )}
      {exportStatus.kind !== 'idle' && (
        <span
          className={`truncate text-xs ${
            exportStatus.kind === 'done' ? 'text-green-600' : 'text-red-600'
          }`}
          title={exportStatus.msg}
        >
          {exportStatus.msg}
        </span>
      )}
      {withPush && pushStatus.kind !== 'idle' && (
        <span
          className={`truncate text-xs ${
            pushStatus.kind === 'done' ? 'text-green-600' : 'text-red-600'
          }`}
          title={pushStatus.msg}
        >
          {pushStatus.msg}
        </span>
      )}
    </div>
  )
}
