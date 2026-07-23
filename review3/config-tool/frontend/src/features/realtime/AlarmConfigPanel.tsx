import { useCallback, useEffect, useState } from 'react'
import { realtimeProjectApi } from '../../lib/api'
import type { AlarmRule, AlarmDirection, AlarmSeverity } from './types'

interface Props {
  projectId: string
}

const emptyRule = (): Omit<AlarmRule, 'id'> => ({
  name: '',
  tag: '',
  direction: 'high' as AlarmDirection,
  limit: 0,
  severity: 'warning' as AlarmSeverity,
  delay_seconds: 0,
  deadband: 0,
  enabled: true,
  message: '',
})

export function AlarmConfigPanel({ projectId }: Props) {
  const [rules, setRules] = useState<AlarmRule[]>([])
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<Omit<AlarmRule, 'id'> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const r = await realtimeProjectApi.listAlarmRules(projectId)
      setRules((r as any) || [])
    } catch (e: any) {
      setError(String(e))
    }
  }, [projectId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleCreate = async () => {
    if (!draft) return
    setError(null)
    try {
      const r = await realtimeProjectApi.createAlarmRule(projectId, { id: '', ...draft })
      setRules((r as any) || [])
      setDraft(null)
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleDelete = async (id: string) => {
    setError(null)
    try {
      const r = await realtimeProjectApi.deleteAlarmRule(projectId, id)
      setRules((r as any) || [])
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleToggle = async (rule: AlarmRule) => {
    setError(null)
    try {
      const r = await realtimeProjectApi.updateAlarmRule(projectId, { ...rule, enabled: !rule.enabled })
      setRules((r as any) || [])
    } catch (e: any) {
      setError(String(e))
    }
  }

  return (
    <section className="space-y-2 rounded-md border border-border bg-card p-3" data-testid="alarm-config-panel">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium">报警规则</span>
        <span className="text-xs text-muted-foreground">({rules.length})</span>
        <button
          type="button"
          onClick={() => setDraft(emptyRule())}
          className="ml-auto rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary"
          data-testid="alarm-add"
        >
          + 新增规则
        </button>
      </div>

      {rules.length === 0 ? (
        <div className="py-3 text-center text-xs text-muted-foreground">暂无报警规则</div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-2 py-1 font-medium">名称</th>
              <th className="px-2 py-1 font-medium">位号</th>
              <th className="px-2 py-1 font-medium">方向</th>
              <th className="px-2 py-1 font-medium">限值</th>
              <th className="px-2 py-1 font-medium">级别</th>
              <th className="px-2 py-1 font-medium">启用</th>
              <th className="px-2 py-1 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className="border-b border-border/40">
                <td className="px-2 py-1">{r.name}</td>
                <td className="px-2 py-1 font-mono">{r.tag}</td>
                <td className="px-2 py-1">{r.direction === 'high' ? '高' : '低'}</td>
                <td className="px-2 py-1">{r.limit}</td>
                <td className="px-2 py-1">{r.severity}</td>
                <td className="px-2 py-1">
                  <input type="checkbox" checked={r.enabled} onChange={() => void handleToggle(r)} />
                </td>
                <td className="px-2 py-1">
                  <button
                    type="button"
                    onClick={() => void handleDelete(r.id)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {draft ? (
        <div className="space-y-2 rounded-md border border-border p-2" data-testid="alarm-draft">
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">名称</span>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">位号</span>
              <input
                value={draft.tag}
                onChange={(e) => setDraft({ ...draft, tag: e.target.value })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">方向</span>
              <select
                value={draft.direction}
                onChange={(e) => setDraft({ ...draft, direction: e.target.value as AlarmDirection })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              >
                <option value="high">高</option>
                <option value="low">低</option>
              </select>
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">级别</span>
              <select
                value={draft.severity}
                onChange={(e) => setDraft({ ...draft, severity: e.target.value as AlarmSeverity })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              >
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="high">high</option>
                <option value="critical">critical</option>
              </select>
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">限值</span>
              <input
                type="number"
                value={draft.limit}
                onChange={(e) => setDraft({ ...draft, limit: Number(e.target.value) })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">延时(秒)</span>
              <input
                type="number"
                value={draft.delay_seconds}
                onChange={(e) => setDraft({ ...draft, delay_seconds: Number(e.target.value) })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">死区</span>
              <input
                type="number"
                value={draft.deadband}
                onChange={(e) => setDraft({ ...draft, deadband: Number(e.target.value) })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
            <label className="space-y-0.5 text-xs">
              <span className="text-muted-foreground">消息</span>
              <input
                value={draft.message}
                onChange={(e) => setDraft({ ...draft, message: e.target.value })}
                className="block w-full rounded border border-border bg-background px-2 py-0.5"
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded border border-border px-2 py-0.5 text-xs hover:bg-secondary"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleCreate()}
              className="rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground"
              data-testid="alarm-save"
            >
              保存
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
          {error}
        </div>
      ) : null}
    </section>
  )
}
