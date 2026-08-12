import { useState, useEffect } from "react"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/Toast"
import {
  monitorApi, type MonitorReportLite, type SubAbnormal, type MonitorSnapshot,
} from "@/lib/api"
import { EventsOn } from "../../wailsjs/runtime/runtime"

const GOOD = "#2f9e6f"
const BAD = "#d44333"
const WARN = "#d9730d"
const TAG_COUNT = 42

// 子异常类型元信息：标签 + 颜色
const ABM_META: Record<number, { label: string; color: string }> = {
  1: { label: "API异常", color: "#666" },
  2: { label: "数据源缺失", color: BAD },
  3: { label: "数据源离线", color: BAD },
  4: { label: "位号异常", color: BAD },
  5: { label: "值停滞", color: WARN },
}

// 拉取租户当前所有活跃子异常
function getActiveSubs(r: MonitorReportLite): { type: number; sub: SubAbnormal }[] {
  const out: { type: number; sub: SubAbnormal }[] = []
  if (r.subAPIFailure.active) out.push({ type: 1, sub: r.subAPIFailure })
  if (r.subDsNotFound.active) out.push({ type: 2, sub: r.subDsNotFound })
  if (r.subDsOffline.active) out.push({ type: 3, sub: r.subDsOffline })
  if (r.subTagBad.active) out.push({ type: 4, sub: r.subTagBad })
  if (r.subValueStale.active) out.push({ type: 5, sub: r.subValueStale })
  return out
}

function fmtTime(t: string): string {
  if (!t) return "-"
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function fmtDateTime(t: string): string {
  if (!t) return "-"
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function MonitorTab() {
  const toast = useToast()
  const [snap, setSnap] = useState<MonitorSnapshot | null>(null)
  const [summaryOpen, setSummaryOpen] = useState(false)

  useEffect(() => {
    monitorApi.snapshot().then((s) => { if (s) setSnap(s) }).catch(() => {})
    const off = EventsOn("monitor:update", (s: MonitorSnapshot) => setSnap(s))
    return () => { off?.() }
  }, [])

  const reports = snap?.cycle.reports || []

  // 统计
  const stats = {
    total: 0, api: 0, dsNotFound: 0, dsOffline: 0, tagBad: 0, valueStale: 0,
    lastUnconfirmed: 0,
  }
  const needConfirm: MonitorReportLite[] = []
  for (const r of reports) {
    if (r.subAPIFailure.active) { stats.total++; stats.api++ }
    if (r.subDsNotFound.active) { stats.total++; stats.dsNotFound++ }
    if (r.subDsOffline.active) { stats.total++; stats.dsOffline++ }
    if (r.subTagBad.active) { stats.total++; stats.tagBad++ }
    if (r.subValueStale.active) { stats.total++; stats.valueStale++ }
    if (!r.abnormal && r.lastAbnType > 0 && !r.lastAbnConfirmed) {
      stats.lastUnconfirmed++
      needConfirm.push(r)
    }
  }

  const confirm = async (tenantID: string, name: string) => {
    try {
      await monitorApi.confirm(tenantID)
      setSnap((prev) => {
        if (!prev) return prev
        const reports = prev.cycle.reports.map((r) =>
          r.tenantId === tenantID ? { ...r, lastAbnConfirmed: true } : r
        )
        return { cycle: { ...prev.cycle, reports } }
      })
      toast(`已确认 ${name}`, "success")
    } catch (err: any) {
      toast(err?.message || String(err), "error")
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">数据源监控</h2>
        <span className="text-[12.5px] text-muted-foreground">
          每 5 秒轮询 · 数据源存活 + 42 位号 · 子异常状态机
        </span>
        <div className="ml-auto flex items-center gap-3">
          {snap && (
            <span className="text-[12px] text-muted-foreground">
              上一轮 {fmtTime(snap.cycle.at)} · {snap.cycle.durMs} ms
            </span>
          )}
        </div>
      </div>

      {/* 异常总览栏 */}
      <div className="px-7 pb-2 flex items-center gap-2 flex-wrap">
        <div className="inline-flex items-center gap-2 rounded-md bg-card border border-border px-3 py-1.5 shadow-sm">
          <span className="text-[12px] text-muted-foreground">总异常</span>
          <span className={`text-[13px] font-semibold ${stats.total > 0 ? "text-destructive" : "text-primary"}`}>
            {stats.total}
          </span>
        </div>
        {([1, 2, 3, 4, 5] as const).map((t) => {
          const count = t === 1 ? stats.api : t === 2 ? stats.dsNotFound : t === 3 ? stats.dsOffline : t === 4 ? stats.tagBad : stats.valueStale
          if (count === 0) return null
          return (
            <span key={t} className="inline-flex items-center gap-1 text-[12px]" style={{ color: ABM_META[t].color }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: ABM_META[t].color }} />
              {ABM_META[t].label} {count}
            </span>
          )
        })}
        {stats.lastUnconfirmed > 0 && (
          <button
            onClick={() => setSummaryOpen(true)}
            className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md text-[12px] text-destructive bg-destructive/10 hover:bg-destructive/15 transition-colors duration-150"
          >
            {stats.lastUnconfirmed} 个未确认的历史异常
          </button>
        )}
      </div>

      <div className="flex-1 overflow-auto px-7 pb-7">
        {reports.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-[12.5px] text-muted-foreground/70">
            <span className="text-2xl">◎</span>
            正在每 5 秒监控全部租户，等待首轮结果…
          </div>
        )}
        {reports.length > 0 && (
          <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow className="border-b border-border bg-secondary">
                  <TableHead className="w-12 text-center">序号</TableHead>
                  <TableHead className="w-40">队名</TableHead>
                  <TableHead className="w-32">租户</TableHead>
                  <TableHead className="w-32">数据源</TableHead>
                  <TableHead className="w-32">位号</TableHead>
                  <TableHead className="w-20 text-center">刷新</TableHead>
                  <TableHead className="w-20 text-right">采样值</TableHead>
                  <TableHead className="w-16 text-center">总状态</TableHead>
                  <TableHead>子异常</TableHead>
                  <TableHead className="w-24">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="[&_td]:py-1">
                {reports.map((r, i) => {
                  const subs = getActiveSubs(r)
                  const lastUnconfirmed = !r.abnormal && r.lastAbnType > 0 && !r.lastAbnConfirmed
                  return (
                    <TableRow key={r.tenantId} className="transition-colors duration-150 hover:bg-muted/20">
                      <TableCell className="text-center text-muted-foreground">{i + 1}</TableCell>
                      <TableCell className="font-medium truncate">{r.name}</TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground truncate">{r.tenantId}</TableCell>
                      <TableCell>
                        {r.subDsNotFound.active ? (
                          <span className="text-[12px]" style={{ color: BAD }}>未找到</span>
                        ) : r.subDsOffline.active ? (
                          <span className="text-[12px]" style={{ color: BAD }}>离线</span>
                        ) : r.dsFound && r.dsAlive ? (
                          <span className="text-[12px]" style={{ color: GOOD }}>在线</span>
                        ) : (
                          <span className="text-[12px] text-muted-foreground/60">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {r.subTagBad.active ? (
                          <span className="text-[12px]" style={{ color: BAD }}>{r.tagGood}/{r.tagTotal}</span>
                        ) : r.tagTotal > 0 ? (
                          <span className="text-[12px]" style={{ color: GOOD }}>{r.tagGood}/{r.tagTotal}</span>
                        ) : (
                          <span className="text-[12px] text-muted-foreground/60">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-center font-mono text-[11px] text-muted-foreground">{fmtTime(r.sampleTime)}</TableCell>
                      <TableCell className="text-right font-mono text-[12px]">{r.sampleValue || "-"}</TableCell>
                      <TableCell className="text-center">
                        {r.abnormal ? (
                          <span className="inline-flex items-center text-destructive text-[12px] font-medium">异常</span>
                        ) : (
                          <span className="inline-flex items-center text-[12px] font-medium" style={{ color: GOOD }}>正常</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {subs.length > 0 ? (
                          <div className="flex flex-col gap-1">
                            {subs.map((s) => (
                              <span key={s.type} className="inline-flex items-center gap-1 text-[11.5px]" title={s.sub.detail}>
                                <span className="w-1.5 h-1.5 rounded-full" style={{ background: ABM_META[s.type].color }} />
                                <span style={{ color: ABM_META[s.type].color }}>{ABM_META[s.type].label}</span>
                                <span className="text-muted-foreground text-[10.5px]">{fmtDateTime(s.sub.since)}</span>
                              </span>
                            ))}
                          </div>
                        ) : lastUnconfirmed ? (
                          <span className="text-[11.5px] text-muted-foreground" title={r.lastAbnDetail}>
                            上次: <span style={{ color: ABM_META[r.lastAbnType]?.color || BAD }}>
                              {ABM_META[r.lastAbnType]?.label || `类型${r.lastAbnType}`}
                            </span>{" "}
                            <span className="text-[10.5px]">{fmtDateTime(r.lastAbnSince)}</span>
                            <span className="text-[10.5px] text-muted-foreground/70 ml-1">(未确认)</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground/60">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {!r.abnormal && r.lastAbnType > 0 && !r.lastAbnConfirmed ? (
                          <button
                            onClick={() => confirm(r.tenantId, r.name)}
                            className="px-2 h-6 rounded-md text-[11.5px] text-primary bg-primary/10 hover:bg-primary/15 transition-colors duration-150"
                          >
                            确认
                          </button>
                        ) : (
                          <span className="text-muted-foreground/60">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* 未确认历史异常详情 */}
      <Modal open={summaryOpen} onClose={() => setSummaryOpen(false)} title="未确认的历史异常" width="w-[720px]">
        {needConfirm.length === 0 ? (
          <div className="text-center py-10 text-[12.5px] text-muted-foreground">无</div>
        ) : (
          <div className="max-h-[60vh] overflow-auto border border-border rounded-lg">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow className="border-b border-border bg-secondary">
                  <TableHead className="w-44">租户</TableHead>
                  <TableHead className="w-40">异常点</TableHead>
                  <TableHead className="w-36 text-center">时间</TableHead>
                  <TableHead>详情</TableHead>
                  <TableHead className="w-20">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="[&_td]:py-1">
                {needConfirm.map((r) => (
                  <TableRow key={r.tenantId}>
                    <TableCell>
                      <div className="font-medium truncate">{r.name}</div>
                      <div className="font-mono text-[10.5px] text-muted-foreground truncate">{r.tenantId}</div>
                    </TableCell>
                    <TableCell>
                      <span className="text-[12px]" style={{ color: ABM_META[r.lastAbnType]?.color || BAD }}>
                        {ABM_META[r.lastAbnType]?.label || `类型${r.lastAbnType}`}
                      </span>
                    </TableCell>
                    <TableCell className="text-center font-mono text-[11px] text-muted-foreground">{fmtDateTime(r.lastAbnSince)}</TableCell>
                    <TableCell className="text-[12px] break-all">{r.lastAbnDetail}</TableCell>
                    <TableCell>
                      <button
                        onClick={() => confirm(r.tenantId, r.name)}
                        className="px-2 h-6 rounded-md text-[11.5px] text-primary bg-primary/10 hover:bg-primary/15 transition-colors duration-150"
                      >
                        确认
                      </button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Modal>
    </div>
  )
}