import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { EmptyState } from "@/components/EmptyState"
import type { Team } from "@/lib/api"

interface Props {
  teams: Team[]
  loading: boolean
  error: string | null
}

export function TeamInfoTab({ teams, loading, error }: Props) {
  if (loading) {
    return <div className="text-center py-16 text-[13px] text-muted-foreground">加载中…</div>
  }
  if (error) {
    return <EmptyState icon="✕" title="加载失败" desc={error} />
  }
  if (teams.length === 0) {
    return <EmptyState icon="∅" title="暂无数据" />
  }

  const playerCount = teams.filter((t) => t.type !== "测试").length
  const testCount = teams.filter((t) => t.type === "测试").length

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-baseline gap-3 px-7 pt-7 pb-3">
        <h2 className="text-[15px] font-semibold">队伍信息</h2>
        <span className="text-[12.5px] text-muted-foreground">
          共 {teams.length} 个租户（{playerCount} 选手 + {testCount} 测试），选手按 zkjs 升序，测试租户放最后
        </span>
      </div>
      <div className="flex-1 overflow-auto px-7 pb-7">
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-border bg-muted/50">
                <TableHead className="w-16 text-center">序号</TableHead>
                <TableHead>队伍名</TableHead>
                <TableHead className="w-40">租户ID</TableHead>
                <TableHead className="w-36">账号</TableHead>
                <TableHead className="w-24">机器</TableHead>
                <TableHead className="w-40">IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {teams.map((t) => (
                <TableRow
                  key={t.tenantId}
                  className={t.type === "测试" ? "bg-[hsl(40,50%,97%)]" : ""}
                >
                  <TableCell className="text-center text-muted-foreground">{t.seq}</TableCell>
                  <TableCell className="font-medium">{t.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.tenantId}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.username}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.machine?.zkjs || "-"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.ip}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
