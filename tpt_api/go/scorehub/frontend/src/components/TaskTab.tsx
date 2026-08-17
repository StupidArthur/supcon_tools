import { useState } from "react"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { EmptyState } from "@/components/EmptyState"
import { useToast } from "@/components/Toast"
import { taskApi, type TeamTaskStats } from "@/lib/api"

interface Props {
  rows: TeamTaskStats[]
  loading: boolean
  error: string | null
  onReload: () => void
}

export function TaskTab({ rows, loading, error, onReload }: Props) {
  const toast = useToast()
  const [refreshing, setRefreshing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    try {
      await onReload()
      toast("任务统计已刷新", "success")
    } catch (err: any) {
      toast(err?.message || String(err), "error")
    } finally {
      setRefreshing(false)
    }
  }

  if (loading && rows.length === 0) {
    return <div className="text-center py-16 text-[13px] text-muted-foreground">加载中…</div>
  }
  if (error) {
    return <EmptyState icon="✕" title="加载失败" desc={error} />
  }

  const total = rows.reduce((s, r) => s + r.total, 0)
  const enabled = rows.reduce((s, r) => s + r.enabled, 0)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">任务管理</h2>
        <span className="text-[12.5px] text-muted-foreground">
          全部选手调度任务 · 共 {total} 个（启用 {enabled}）· 按启用数升序
        </span>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="ml-auto inline-flex items-center gap-1.5 h-7 px-3 rounded-md bg-primary text-primary-foreground text-[12px] font-medium shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
        >
          <svg
            className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 12a9 9 0 1 1-2.64-6.36L21 8" />
            <polyline points="21 3 21 8 16 8" />
          </svg>
          {refreshing ? "刷新中…" : "刷新"}
        </button>
      </div>
      <div className="flex-1 overflow-auto px-7 pb-7">
        <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="border-b border-border bg-secondary">
                <TableHead className="w-16 text-center">序号</TableHead>
                <TableHead className="w-48">队伍名</TableHead>
                <TableHead className="w-40">租户ID</TableHead>
                <TableHead className="w-24 text-center">总任务数</TableHead>
                <TableHead className="w-24 text-center">启用任务数</TableHead>
                <TableHead className="min-w-[200px]">启用任务明细</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="[&_td]:py-1">
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6 text-[12.5px]">
                    暂无数据
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((r) => (
                  <TableRow key={r.tenantId} className="transition-colors duration-150 hover:bg-muted/20 align-top">
                    <TableCell className="text-center text-muted-foreground">{r.seq}</TableCell>
                    <TableCell className="font-medium truncate">{r.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground truncate">{r.tenantId}</TableCell>
                    <TableCell className="font-mono text-xs text-center">{r.total}</TableCell>
                    <TableCell className="text-center">
                      <span className="font-mono text-xs font-medium text-primary">{r.enabled}</span>
                    </TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground leading-relaxed whitespace-normal break-all">
                      {r.enabledDetail || "-"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}