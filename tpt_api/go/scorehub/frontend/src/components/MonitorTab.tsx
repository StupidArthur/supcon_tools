import { useState, useEffect } from "react"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { Modal } from "@/components/ui/modal"
import { monitorApi, type MonitorReportLite, type MonitorSnapshot } from "@/lib/api"
import { EventsOn } from "../../wailsjs/runtime/runtime"

const GOOD = "#2f9e6f"
const BAD = "#d44333"
const WARN = "#d9730d"
const TAG_COUNT = 39

function Dot({ color }: { color: string }) {
  return <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: color }} />
}

function subStatus(r: MonitorReportLite): { color: string; text: string }[] {
  const out: { color: string; text: string }[] = []
  if (!r.dsFound) {
    out.push({ color: BAD, text: "未找到数据源" })
  } else if (r.dsAlive) {
    out.push({ color: GOOD, text: "数据源在线" })
  } else {
    out.push({ color: BAD, text: "数据源离线" })
  }
  if (r.tagTotal === 0) {
    out.push({ color: WARN, text: "位号未读到" })
  } else if (r.tagGood === r.tagTotal) {
    out.push({ color: GOOD, text: `位号 ${r.tagGood}/${r.tagTotal} GOOD` })
  } else {
    out.push({ color: BAD, text: `位号 ${r.tagGood}/${r.tagTotal} GOOD` })
  }
  return out
}

function isAbnormal(r: MonitorReportLite): boolean {
  if (r.error || !r.dsFound || !r.dsAlive) return true
  return r.tagTotal !== TAG_COUNT || r.tagGood !== TAG_COUNT
}

function fmtTime(t: string): string {
  if (!t) return "-"
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function BadDetail({ r }: { r: MonitorReportLite }) {
  return (
    <div className="flex flex-col gap-1.5 text-[12px]">
      <div>{r.dsFound ? `数据源 ${r.dsName}` : "数据源未找到"} · {r.dsTarUrl || "-"}</div>
      <div>位号 {r.tagGood}/{r.tagTotal} GOOD</div>
      {r.badTags && r.badTags.length > 0 && (
        <div className="font-mono text-[11px] text-destructive/80 leading-relaxed break-all">
          BAD: {r.badTags.join(", ")}
        </div>
      )}
      {r.error && <div className="text-destructive break-all">{r.error}</div>}
    </div>
  )
}

export function MonitorTab() {
  const [snap, setSnap] = useState<MonitorSnapshot | null>(null)
  const [histOpen, setHistOpen] = useState(false)

  useEffect(() => {
    // 切入即拉取最新缓存快照，立即渲染。
    monitorApi.snapshot().then((s) => { if (s) setSnap(s) }).catch(() => {})
    const off = EventsOn("monitor:update", (s: MonitorSnapshot) => setSnap(s))
    return () => {
      off?.()
    }
  }, [])

  const reports = snap?.cycle.reports || []
  const abnormalCount = reports.filter(isAbnormal).length

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">数据源监控</h2>
        <span className="text-[12.5px] text-muted-foreground">
          每 5 秒轮询全部租户 · 数据源存活 + 39 位号质量（GOOD=192）
        </span>
        <div className="ml-auto flex items-center gap-3">
          {snap ? (
            <span className="text-[12px] text-muted-foreground">
              上一轮 {fmtTime(snap.cycle.at)} · {snap.cycle.durMs} ms · {snap.abnormalCycles.length} 个异常周期
            </span>
          ) : (
            <span className="text-[12px] text-muted-foreground animate-pulse">等待首轮监控结果…</span>
          )}
        </div>
      </div>

      <div className="px-7 pb-2 flex items-center gap-3">
        <div className="inline-flex items-center gap-2 rounded-md bg-card border border-border px-3 py-1.5 shadow-sm">
          <span className="text-[12px] text-muted-foreground">本轮异常</span>
          <span className={`text-[13px] font-semibold ${abnormalCount > 0 ? "text-destructive" : "text-primary"}`}>
            {abnormalCount}
          </span>
          <span className="text-[12px] text-muted-foreground">/ {reports.length} 个租户</span>
        </div>
        <div className="inline-flex items-center gap-4 px-3 py-1.5 text-[12px] text-muted-foreground">
          <span><Dot color={GOOD} />正常</span>
          <span><Dot color={BAD} />异常</span>
          <span><Dot color={WARN} />未读到</span>
          {snap && (snap.abnormalCycles?.length || 0) > 0 && (
            <button
              onClick={() => setHistOpen(true)}
              className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md text-destructive bg-destructive/10 hover:bg-destructive/15 transition-colors duration-150"
            >
              <Dot color={BAD} />
              最近 {snap.abnormalCycles.length} 个异常周期
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto px-7 pb-7">
        {!snap && (
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
                  <TableHead className="w-40">数据源</TableHead>
                  <TableHead className="w-40">位号</TableHead>
                  <TableHead className="w-20 text-center">状态</TableHead>
                  <TableHead className="w-24 text-center">刷新时间</TableHead>
                  <TableHead className="w-28 text-right">FT60201.PV</TableHead>
                  <TableHead>备注 / 异常</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="[&_td]:py-1">
                {reports.map((r, i) => (
                  <TableRow key={r.tenantId} className="transition-colors duration-150 hover:bg-muted/20">
                    <TableCell className="text-center text-muted-foreground">{i + 1}</TableCell>
                    <TableCell className="font-medium truncate">{r.name}</TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground truncate">{r.tenantId}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-0.5 text-[12px]">
                        {subStatus(r).slice(0, 1).map((s, si) => (
                          <span key={si} className={s.color === GOOD ? "font-medium" : ""} style={{ color: s.color }}>
                            <Dot color={s.color} />{s.text}
                          </span>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="text-[12px]">
                        {subStatus(r).slice(1).map((s, si) => (
                          <span key={si} className={s.color === GOOD ? "font-medium" : ""} style={{ color: s.color }}>
                            <Dot color={s.color} />{s.text}
                          </span>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-center">
                      {isAbnormal(r) ? (
                        <span className="inline-flex items-center text-destructive text-[12px] font-medium"><Dot color={BAD} />异常</span>
                      ) : (
                        <span className="inline-flex items-center text-[12px] font-medium" style={{ color: GOOD }}><Dot color={GOOD} />正常</span>
                      )}
                    </TableCell>
                    <TableCell className="text-center font-mono text-[11px] text-muted-foreground">{r.sampleTime || "-"}</TableCell>
                    <TableCell className="text-right font-mono text-[12px]">{r.sampleValue || "-"}</TableCell>
                    <TableCell>
                      {isAbnormal(r) ? <BadDetail r={r} /> : <span className="text-muted-foreground/60">-</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <Modal open={histOpen} onClose={() => setHistOpen(false)} title="最近异常周期详情" width="w-[720px]">
        {snap && (snap.abnormalCycles?.length || 0) === 0 ? (
          <div className="text-center py-10 text-[12.5px] text-muted-foreground">暂无异常周期</div>
        ) : (
          snap && (
            <div className="flex flex-col gap-3 max-h-[60vh] overflow-auto">
              {snap.abnormalCycles.map((cy, i) => (
                <div key={i} className="border border-border rounded-lg">
                  <div className="px-3 py-2 border-b border-border text-[11.5px] text-muted-foreground bg-muted/30">
                    周期 {fmtTime(cy.at)} · {cy.reports.length} 个租户异常
                  </div>
                  <div className="p-3 flex flex-col gap-2.5">
                    {cy.reports.map((r) => (
                      <div key={r.tenantId} className="flex items-start gap-2">
                        <span className="text-[12px] font-medium w-44 truncate flex-shrink-0">{r.name}</span>
                        <div className="flex-1 min-w-0"><BadDetail r={r} /></div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </Modal>
    </div>
  )
}