import { useEffect, useState } from "react"
import { EmptyState } from "@/components/EmptyState"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/Toast"
import { batchApi, type EvalConfig, type ClearAllResult } from "@/lib/api"

interface Props {
  config: EvalConfig | null
  loading: boolean
  error: string | null
  onReload: () => void
}

function Toggle({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="inline-flex rounded-md bg-muted p-0.5">
      {[1, 0].map((v) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`px-3.5 h-7 rounded text-[12px] font-medium transition-all duration-150 ${
            value === v ? "bg-card shadow-sm text-primary" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {v === 1 ? "开" : "关"}
        </button>
      ))}
    </div>
  )
}

function StatusText({ v }: { v: number }) {
  return v === 1 ? (
    <span className="text-primary font-medium">开启</span>
  ) : (
    <span className="text-muted-foreground">关闭</span>
  )
}

export function BatchTab({ config, loading, error, onReload }: Props) {
  const toast = useToast()
  const [prac, setPrac] = useState(1)
  const [exam, setExam] = useState(0)
  const [duration, setDuration] = useState("")
  const [delay, setDelay] = useState("")
  const [saving, setSaving] = useState(false)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [clearResult, setClearResult] = useState<ClearAllResult | null>(null)

  useEffect(() => {
    if (config) {
      setPrac(config.pracLoadEnabled)
      setExam(config.examLoadEnabled)
      setDuration(String(config.evalDurationMinutes))
      setDelay(String(config.startWorktimeDelayMinutes ?? 0))
    }
  }, [config])

  const save = async () => {
    const mins = Number(duration)
    if (!Number.isFinite(mins) || mins <= 0) {
      toast("评估时长需为正整数（分钟）", "error")
      return
    }
    const del = Number(delay)
    if (!Number.isFinite(del) || del < 0) {
      toast("评分时间延迟需为非负整数（分钟）", "error")
      return
    }
    setSaving(true)
    try {
      const res = await batchApi.updateEvalConfig(prac, exam, Math.round(mins), Math.round(del))
      if (res.error) {
        toast(res.error, "error")
      } else {
        toast("评估配置已保存", "success")
        onReload()
      }
    } catch (err: any) {
      toast(err?.message || String(err), "error")
    } finally {
      setSaving(false)
    }
  }

  const doClear = async () => {
    setConfirmOpen(false)
    setClearing(true)
    setClearResult(null)
    try {
      const res = await batchApi.clearAllScores()
      setClearResult(res)
      if (res.failed === 0) {
        toast(`已清空全部 ${res.success} 个选手租户的评分记录`, "success")
      } else {
        toast(`清空完成：成功 ${res.success}，失败 ${res.failed}`, "error")
      }
    } catch (err: any) {
      toast(err?.message || String(err), "error")
    } finally {
      setClearing(false)
    }
  }

  if (loading) {
    return <div className="text-center py-16 text-[13px] text-muted-foreground">加载中…</div>
  }
  if (error) {
    return <EmptyState icon="✕" title="加载失败" desc={error} />
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-baseline gap-3 px-7 pt-6 pb-3">
        <h2 className="text-[15px] font-semibold">批量管理</h2>
        <span className="text-[12.5px] text-muted-foreground">全局评估参数，作用于所有租户</span>
      </div>
      <div className="flex-1 overflow-auto px-7 pb-7">
        <div className="flex flex-col gap-3.5 max-w-[560px]">
          <div className="bg-card border border-border rounded-lg shadow-sm">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <span className="text-[13px] font-medium">当前配置</span>
              <button
                onClick={onReload}
                className="text-[12px] text-primary hover:bg-primary/10 rounded-md px-2 h-6 transition-colors duration-150"
              >
                刷新
              </button>
            </div>
            <div className="px-4 py-3 flex flex-col gap-2.5 text-[12.5px]">
              {config ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">练习工况</span>
                    <StatusText v={config.pracLoadEnabled} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">考试工况</span>
                    <StatusText v={config.examLoadEnabled} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">评估时长</span>
                    <span className="font-mono">{config.evalDurationMinutes} 分钟</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">评分时间延迟</span>
                    <span className="font-mono">{config.startWorktimeDelayMinutes ?? 0} 分钟</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">最近更新</span>
                    <span className="font-mono text-[11.5px] text-muted-foreground">{config.updateTime || "-"}</span>
                  </div>
                </>
              ) : (
                <div className="text-muted-foreground/70 text-center py-3">暂无配置</div>
              )}
            </div>
          </div>

          <div className="bg-card border border-border rounded-lg shadow-sm">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-[13px] font-medium">修改配置</span>
            </div>
            <div className="px-4 py-3 flex flex-col gap-3.5">
              <div className="flex items-center justify-between text-[12.5px]">
                <span className="text-muted-foreground">练习工况</span>
                <Toggle value={prac} onChange={setPrac} />
              </div>
              <div className="flex items-center justify-between text-[12.5px]">
                <span className="text-muted-foreground">考试工况</span>
                <Toggle value={exam} onChange={setExam} />
              </div>
              <div className="flex items-center justify-between text-[12.5px]">
                <span className="text-muted-foreground">评估时长（分钟）</span>
                <input
                  type="number"
                  min={1}
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  className="w-28 h-8 rounded-md border border-input bg-background px-2.5 text-[12.5px] font-mono focus:outline-none focus:ring-2 focus:ring-ring transition-all duration-150"
                />
              </div>
              <div className="flex items-center justify-between text-[12.5px]">
                <span className="text-muted-foreground">评分时间延迟（分钟）</span>
                <input
                  type="number"
                  min={0}
                  value={delay}
                  onChange={(e) => setDelay(e.target.value)}
                  className="w-28 h-8 rounded-md border border-input bg-background px-2.5 text-[12.5px] font-mono focus:outline-none focus:ring-2 focus:ring-ring transition-all duration-150"
                />
              </div>
              <div className="flex justify-end pt-1">
                <button
                  onClick={save}
                  disabled={saving}
                  className="h-8 px-4 rounded-md bg-primary text-primary-foreground text-[12.5px] font-medium shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
                >
                  {saving ? "保存中…" : "保存配置"}
                </button>
              </div>
            </div>
          </div>

          <div className="bg-card border border-destructive/40 rounded-lg shadow-sm">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <div>
                <span className="text-[13px] font-medium text-destructive">危险操作</span>
                <p className="text-[11.5px] text-muted-foreground mt-0.5">清空所有选手租户的评分记录（不可恢复）</p>
              </div>
              <button
                onClick={() => setConfirmOpen(true)}
                disabled={clearing}
                className="h-8 px-4 rounded-md bg-destructive text-destructive-foreground text-[12.5px] font-medium shadow-sm hover:opacity-90 transition-all duration-150 disabled:opacity-60"
              >
                {clearing ? "清空中…" : "清空所有租户评分记录"}
              </button>
            </div>
            {clearResult && (
              <div className="px-4 py-3 text-[12px]">
                <div className="flex gap-4 mb-2">
                  <span>
                    成功 <span className="text-primary font-medium">{clearResult.success}</span>
                  </span>
                  <span>
                    失败 <span className="text-destructive font-medium">{clearResult.failed}</span>
                  </span>
                </div>
                {clearResult.failed > 0 && (
                  <div className="text-muted-foreground flex flex-col gap-0.5">
                    {clearResult.items.filter((i) => !i.success).map((i) => (
                      <div key={i.tenantId} className="truncate">
                        <span className="text-destructive">✕</span> {i.name}（{i.tenantId}）: {i.error}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="确认清空所有评分记录"
        width="w-[460px]"
        footer={
          <>
            <button
              onClick={() => setConfirmOpen(false)}
              className="h-8 px-4 rounded-md bg-secondary text-secondary-foreground text-[12.5px] font-medium hover:opacity-90 transition-all duration-150"
            >
              取消
            </button>
            <button
              onClick={doClear}
              className="h-8 px-4 rounded-md bg-destructive text-destructive-foreground text-[12.5px] font-medium shadow-sm hover:opacity-90 transition-all duration-150"
            >
              确认清空
            </button>
          </>
        }
      >
        <div className="text-[12.5px] leading-relaxed">
          <p>此操作将遍历 <span className="font-semibold">全部 {config ? 39 : 39} 个选手租户</span>，逐个清空其评分记录，<span className="text-destructive font-medium">不可恢复</span>。</p>
          <p className="mt-2 text-muted-foreground">请确认生产环境中不需要保留当前成绩，再进行操作。</p>
        </div>
      </Modal>
    </div>
  )
}