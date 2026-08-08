import { useMemo, useState } from "react"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { EmptyState } from "@/components/EmptyState"
import type { Team } from "@/lib/api"

type SortKey = "seq" | "name" | "tenantId" | "username" | "zkjs" | "ip"
type SortDir = "asc" | "desc"

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" })

function sortValue(t: Team, key: SortKey): string {
  switch (key) {
    case "name": return t.name
    case "tenantId": return t.tenantId
    case "username": return t.username
    case "zkjs": return t.machine?.zkjs || ""
    default: return ""
  }
}

function compareTeams(a: Team, b: Team, key: SortKey): number {
  if (key === "seq") return a.seq - b.seq
  if (key === "ip") {
    const pa = a.ip.split(".").map(Number)
    const pb = b.ip.split(".").map(Number)
    for (let i = 0; i < 4; i++) {
      const d = (pa[i] || 0) - (pb[i] || 0)
      if (d !== 0) return d
    }
    return 0
  }
  return collator.compare(sortValue(a, key), sortValue(b, key))
}

interface SortableHeadProps {
  label: string
  k: SortKey
  sortKey: SortKey
  sortDir: SortDir
  onSort: (k: SortKey) => void
  className?: string
  center?: boolean
}

function SortableHead({ label, k, sortKey, sortDir, onSort, className, center }: SortableHeadProps) {
  const active = sortKey === k
  return (
    <TableHead className={className}>
      <button
        onClick={() => onSort(k)}
        className={`inline-flex items-center gap-1 font-medium transition-colors duration-150 hover:text-foreground ${active ? "text-primary" : ""} ${center ? "w-full justify-center" : ""}`}
      >
        {label}
        <span className={`text-[9px] leading-none ${active ? "text-primary" : "text-muted-foreground/30"}`}>
          {active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </TableHead>
  )
}

interface Props {
  teams: Team[]
  loading: boolean
  error: string | null
}

export function TeamInfoTab({ teams, loading, error }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("seq")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      setSortDir("asc")
    }
  }

  const sortedTeams = useMemo(() => {
    const players = teams.filter((t) => t.type !== "测试")
    const tests = teams.filter((t) => t.type === "测试")
    const cmp = (a: Team, b: Team) => compareTeams(a, b, sortKey) * (sortDir === "asc" ? 1 : -1)
    return [...players.sort(cmp), ...tests.sort(cmp)]
  }, [teams, sortKey, sortDir])

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
      <div className="flex items-baseline gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">队伍信息</h2>
        <span className="text-[12.5px] text-muted-foreground">
          共 {teams.length} 个租户 · <span className="text-primary font-medium">{playerCount} 选手</span> + {testCount} 测试 · 点击表头排序
        </span>
      </div>
      <div className="flex-1 overflow-auto px-7 pb-7">
        <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="border-b border-border bg-secondary">
                <SortableHead label="序号" k="seq" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-16 text-center" center />
                <SortableHead label="队伍名" k="name" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-56" />
                <SortableHead label="租户ID" k="tenantId" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-44" />
                <SortableHead label="账号" k="username" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-40" />
                <SortableHead label="机器" k="zkjs" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-28" />
                <SortableHead label="IP" k="ip" sortKey={sortKey} sortDir={sortDir} onSort={onSort} className="w-44" />
              </TableRow>
            </TableHeader>
            <TableBody className="[&_td]:py-1">
              {sortedTeams.map((t) => (
                <TableRow
                  key={t.tenantId}
                  className={`transition-colors duration-150 hover:bg-muted/20 ${t.type === "测试" ? "bg-muted/30" : ""}`}
                >
                  <TableCell className="text-center text-muted-foreground">{t.seq}</TableCell>
                  <TableCell className="font-medium truncate">
                    {t.name}
                    {t.type === "测试" && (
                      <span className="ml-2 px-1.5 py-0.5 rounded-sm bg-secondary text-muted-foreground text-[10.5px] font-normal align-middle">
                        测试
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{t.tenantId}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{t.username}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{t.machine?.zkjs || "-"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{t.ip}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
