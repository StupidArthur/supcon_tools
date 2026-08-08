import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { EmptyState } from "@/components/EmptyState"
import type { RankingItem } from "@/lib/api"

interface Props {
  items: RankingItem[]
  loading: boolean
  error: string | null
  onReload: () => void
}

function Score({ value }: { value?: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground/50">-</span>
  }
  return <>{value.toFixed(2)}</>
}

function RankBadge({ rank }: { rank: number }) {
  if (rank >= 1 && rank <= 3) {
    return (
      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-[12px] font-semibold">
        {rank}
      </span>
    )
  }
  return <span className="text-muted-foreground">{rank}</span>
}

export function RankingTab({ items, loading, error, onReload }: Props) {
  if (loading) {
    return <div className="text-center py-16 text-[13px] text-muted-foreground">加载中…</div>
  }
  if (error) {
    return <EmptyState icon="✕" title="加载失败" desc={error} />
  }
  if (items.length === 0) {
    return <EmptyState icon="∅" title="暂无排名数据" />
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">成绩排名</h2>
        <span className="text-[12.5px] text-muted-foreground">
          总分 = 控制最优×0.8 + 软测量×0.2 · 同分同排名
        </span>
        <button
          onClick={onReload}
          disabled={loading}
          className="ml-auto inline-flex items-center gap-1.5 h-7 px-3 rounded-md bg-primary text-primary-foreground text-[12px] font-medium shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
        >
          <svg
            className={`w-3 h-3 ${loading ? "animate-spin" : ""}`}
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
          刷新
        </button>
      </div>
      <div className="flex-1 overflow-auto px-7 pb-7">
        <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="border-b border-border bg-secondary">
                <TableHead className="w-20 text-center">名次</TableHead>
                <TableHead className="w-56">队伍名</TableHead>
                <TableHead className="w-44">租户ID</TableHead>
                <TableHead className="w-32 text-right">控制最优</TableHead>
                <TableHead className="w-32 text-right">软测量</TableHead>
                <TableHead className="w-32 text-right">总分</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="[&_td]:py-1">
              {items.map((it) => (
                <TableRow key={it.tenantId} className="transition-colors duration-150 hover:bg-muted/20">
                  <TableCell className="text-center">
                    <RankBadge rank={it.rank} />
                  </TableCell>
                  <TableCell className="font-medium truncate">{it.name || it.tenantId}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{it.tenantId}</TableCell>
                  <TableCell className="font-mono text-xs text-right">
                    <Score value={it.controlScore} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-right">
                    <Score value={it.softSensorScore} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-right font-medium">
                    <Score value={it.totalScore} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
