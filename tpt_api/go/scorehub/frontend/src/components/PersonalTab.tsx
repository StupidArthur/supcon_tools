import { useState } from "react"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { Modal } from "@/components/ui/modal"
import { EmptyState } from "@/components/EmptyState"
import { useToast } from "@/components/Toast"
import { personalApi, type PersonalRow, type TenantDetail } from "@/lib/api"

interface Props {
  rows: PersonalRow[]
  loading: boolean
  error: string | null
  onReload: () => void
}

const statusText: Record<number, { label: string; cls: string }> = {
  1: { label: "评估中", cls: "text-muted-foreground" },
  2: { label: "评估完成", cls: "text-primary" },
  3: { label: "评估失败", cls: "text-destructive" },
}

function Score({ value }: { value?: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground/50">-</span>
  }
  return <>{value.toFixed(2)}</>
}

function fmt(value?: number | null): string {
  if (value === null || value === undefined) return "-"
  return value.toFixed(2)
}

function DetailContent({ detail }: { detail: TenantDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="text-[12.5px] font-medium mb-2">控制成绩记录（{detail.scoreRecords.length}）</div>
        {detail.scoreRecords.length === 0 ? (
          <div className="text-[12px] text-muted-foreground/70 py-3 text-center bg-muted/30 rounded-md">暂无控制成绩记录</div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-b border-border bg-secondary">
                  <TableHead className="w-24">状态</TableHead>
                  <TableHead className="w-24 text-right">评分</TableHead>
                  <TableHead className="w-14 text-center">最优</TableHead>
                  <TableHead className="w-48">工况时间范围</TableHead>
                  <TableHead>子指标 sci / se / ssafe / ssmi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.scoreRecords.map((r) => {
                  const st = statusText[r.status] || { label: `状态${r.status}`, cls: "text-muted-foreground" }
                  return (
                    <TableRow key={r.id}>
                      <TableCell className={`text-xs ${st.cls}`}>{st.label}</TableCell>
                      <TableCell className="font-mono text-xs text-right"><Score value={r.score} /></TableCell>
                      <TableCell className="text-xs text-center">{r.isBest ? "是" : "-"}</TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">
                        {r.startWorktime || "-"} ~ {r.endWorktime || "-"}
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">
                        {fmt(r.sci)} / {fmt(r.se)} / {fmt(r.ssafe)} / {fmt(r.ssmi)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      <div>
        <div className="text-[12.5px] font-medium mb-2">软测量上传文件（{detail.files.length}）</div>
        {detail.files.length === 0 ? (
          <div className="text-[12px] text-muted-foreground/70 py-3 text-center bg-muted/30 rounded-md">暂无上传文件</div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-b border-border bg-secondary">
                  <TableHead>文件名</TableHead>
                  <TableHead className="w-44">上传时间</TableHead>
                  <TableHead className="w-24 text-right">评分</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.files.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-mono text-xs truncate">{f.fileName || "-"}</TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground">{f.uploadTime || "-"}</TableCell>
                    <TableCell className="font-mono text-xs text-right"><Score value={f.score} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  )
}

export function PersonalTab({ rows, loading, error, onReload }: Props) {
  const toast = useToast()
  const [detailRow, setDetailRow] = useState<PersonalRow | null>(null)
  const [detail, setDetail] = useState<TenantDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [confirmRow, setConfirmRow] = useState<PersonalRow | null>(null)
  const [cleaning, setCleaning] = useState(false)

  const openDetail = async (row: PersonalRow) => {
    setDetailRow(row)
    setDetail(null)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const d = await personalApi.detail(row.tenantId)
      setDetail(d)
    } catch (err: any) {
      setDetailError(err?.message || String(err))
    } finally {
      setDetailLoading(false)
    }
  }

  const doCleanup = async () => {
    if (!confirmRow) return
    const row = confirmRow
    setCleaning(true)
    try {
      const res = await personalApi.cleanup(row.tenantId)
      if (res.error) {
        toast(res.error, "error")
      } else {
        toast(`已清空「${row.name}」的评分数据`, "success")
        setConfirmRow(null)
        onReload()
      }
    } catch (err: any) {
      toast(err?.message || String(err), "error")
    } finally {
      setCleaning(false)
    }
  }

  if (loading) {
    return <div className="text-center py-16 text-[13px] text-muted-foreground">加载中…</div>
  }
  if (error) {
    return <EmptyState icon="✕" title="加载失败" desc={error} />
  }
  if (rows.length === 0) {
    return <EmptyState icon="∅" title="暂无数据" />
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">个性化管理</h2>
        <span className="text-[12.5px] text-muted-foreground">
          共 {rows.length} 个租户 · 查看详情、清空单个租户评分记录
        </span>
        <button
          onClick={onReload}
          disabled={loading}
          className="ml-auto inline-flex items-center gap-1.5 h-7 px-3.5 rounded-md bg-primary text-primary-foreground text-[12px] font-medium shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
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
                <TableHead className="w-16 text-center">序号</TableHead>
                <TableHead className="w-56">队伍名</TableHead>
                <TableHead className="w-40">租户</TableHead>
                <TableHead className="w-36">账号</TableHead>
                <TableHead className="w-52">成绩</TableHead>
                <TableHead className="w-28">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="[&_td]:py-1">
              {rows.map((r) => (
                <TableRow key={r.tenantId} className="transition-colors duration-150 hover:bg-muted/20">
                  <TableCell className="text-center text-muted-foreground">{r.seq}</TableCell>
                  <TableCell className="font-medium truncate">{r.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{r.tenantId}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground truncate">{r.username}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs"><Score value={r.totalScore} /></span>
                      <button
                        onClick={() => openDetail(r)}
                        className="px-2 h-6 rounded-md text-[11.5px] text-primary hover:bg-primary/10 transition-colors duration-150"
                      >
                        详情
                      </button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <button
                      onClick={() => setConfirmRow(r)}
                      className="px-2 h-6 rounded-md text-[11.5px] text-destructive hover:bg-destructive/10 transition-colors duration-150"
                    >
                      清空
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <Modal
        open={detailRow !== null}
        onClose={() => setDetailRow(null)}
        title={`成绩详情 · ${detailRow?.name || ""}（${detailRow?.tenantId || ""}）`}
        width="w-[760px]"
      >
        {detailLoading && <div className="text-center py-10 text-[12.5px] text-muted-foreground">加载中…</div>}
        {detailError && <EmptyState icon="✕" title="加载失败" desc={detailError} />}
        {detail && !detailLoading && !detailError && <DetailContent detail={detail} />}
      </Modal>

      <Modal
        open={confirmRow !== null}
        onClose={() => !cleaning && setConfirmRow(null)}
        title="清空评分记录"
        width="w-[440px]"
        footer={
          <>
            <button
              onClick={() => setConfirmRow(null)}
              disabled={cleaning}
              className="h-8 px-3.5 rounded-md text-[12.5px] font-medium text-foreground hover:bg-muted transition-colors duration-150 disabled:opacity-60"
            >
              取消
            </button>
            <button
              onClick={doCleanup}
              disabled={cleaning}
              className="h-8 px-3.5 rounded-md text-[12.5px] font-medium bg-destructive text-destructive-foreground shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
            >
              {cleaning ? "清空中…" : "确认清空"}
            </button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed">
          确定要清空队伍「<span className="font-semibold">{confirmRow?.name}</span>」（{confirmRow?.tenantId}）的全部成绩记录和已上传文件吗？
        </p>
        <p className="text-[12px] text-destructive mt-2">此操作不可恢复，请谨慎操作。</p>
      </Modal>
    </div>
  )
}
