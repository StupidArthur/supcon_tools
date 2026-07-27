import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { api, type Config } from '@/lib/api'

export function ConfigDialog({
  config,
  onClose,
}: {
  config: Config
  onClose: () => void
}) {
  const [cfg, setCfg] = useState<Config>(config)
  const [logPath, setLogPath] = useState('')
  const [newURL, setNewURL] = useState('')
  const [testStatus, setTestStatus] = useState<{ kind: 'idle' | 'done' | 'error'; msg: string }>({
    kind: 'idle',
    msg: '',
  })

  useEffect(() => {
    api.getLogPath().then(setLogPath).catch(() => {})
  }, [])

  const save = async () => {
    const res = await api.saveConfig(cfg)
    if (res.success) {
      alert('配置已保存')
      onClose()
    } else {
      alert('保存失败：' + res.error)
    }
  }

  const testWebhook = async () => {
    if (!cfg.webhookUrl || !cfg.webhookUrl.trim()) {
      setTestStatus({ kind: 'error', msg: '未填写 webhook URL' })
      return
    }
    setTestStatus({ kind: 'idle', msg: '' })
    try {
      const res = await api.testWebhook(cfg.webhookUrl.trim())
      if (res.success) {
        setTestStatus({ kind: 'done', msg: '已发送，请到群机器人查看' })
      } else {
        setTestStatus({ kind: 'error', msg: res.error || '失败' })
      }
    } catch (e) {
      setTestStatus({ kind: 'error', msg: String(e) })
    }
  }

  const addCluster = () => {
    if (!newURL.trim()) return
    const id = 'cluster-' + Date.now()
    setCfg({ ...cfg, clusters: [...cfg.clusters, { id, platformUrl: newURL.trim() }] })
    setNewURL('')
  }

  const removeCluster = (id: string) => {
    setCfg({ ...cfg, clusters: cfg.clusters.filter((c) => c.id !== id) })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="max-h-[85vh] w-[520px] overflow-y-auto rounded-xl bg-card p-6 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-4 text-base font-semibold">配置</h2>

        {/* 采样间隔 */}
        <div className="mb-5">
          <div className="mb-2 text-xs font-medium text-muted-foreground">采样设置</div>
          <Field label="采样间隔（秒）">
            <input type="number" className="input" value={cfg.sampleEvery}
              onChange={(e) => setCfg({ ...cfg, sampleEvery: Number(e.target.value) })} />
          </Field>
          <div className="mt-3">
            <Field label="单集群节点并发数（1~200）">
              <input type="number" min={1} max={200} className="input" value={cfg.detailNodeConcurrency ?? 50}
                onChange={(e) => setCfg({ ...cfg, detailNodeConcurrency: Number(e.target.value) })} />
            </Field>
          </div>
        </div>

        {/* 全局报警阈值 */}
        <div className="mb-5">
          <div className="mb-2 text-xs font-medium text-muted-foreground">全局报警阈值（%）</div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="节点 CPU"><input type="number" className="input" value={cfg.thresholds.nodeCpu} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, nodeCpu: Number(e.target.value) } })} /></Field>
            <Field label="节点内存"><input type="number" className="input" value={cfg.thresholds.nodeMem} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, nodeMem: Number(e.target.value) } })} /></Field>
            <Field label="节点 GPU"><input type="number" className="input" value={cfg.thresholds.nodeGpu} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, nodeGpu: Number(e.target.value) } })} /></Field>
            <Field label="进程 CPU"><input type="number" className="input" value={cfg.thresholds.workerCpu} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, workerCpu: Number(e.target.value) } })} /></Field>
            <Field label="进程内存"><input type="number" className="input" value={cfg.thresholds.workerMem} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, workerMem: Number(e.target.value) } })} /></Field>
            <Field label="进程 GPU"><input type="number" className="input" value={cfg.thresholds.workerGpu} onChange={(e) => setCfg({ ...cfg, thresholds: { ...cfg.thresholds, workerGpu: Number(e.target.value) } })} /></Field>
          </div>
        </div>

        {/* 集群列表（只填 URL） */}
        <div className="mb-5">
          <div className="mb-2 text-xs font-medium text-muted-foreground">集群列表（{cfg.clusters.length}）· 集群名即 URL</div>
          <div className="space-y-1">
            {cfg.clusters.map((cl) => (
              <div key={cl.id} className="flex items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 truncate font-mono text-xs">{cl.platformUrl}</span>
                <button onClick={() => removeCluster(cl.id)} className="text-xs text-destructive hover:underline">删除</button>
              </div>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input
              className="input flex-1 font-mono text-xs"
              placeholder="http://host:port"
              value={newURL}
              onChange={(e) => setNewURL(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addCluster() }}
            />
            <Button size="sm" variant="outline" onClick={addCluster}>添加</Button>
          </div>
        </div>

        {/* Webhook 推送 */}
        <div className="mb-5">
          <div className="mb-2 text-xs font-medium text-muted-foreground">告警推送 · 企业微信群机器人（可选）</div>
          <Field label="Webhook URL（留空则不推送）">
            <input
              className="input font-mono text-xs"
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
              value={cfg.webhookUrl || ''}
              onChange={(e) => setCfg({ ...cfg, webhookUrl: e.target.value })}
            />
          </Field>
          <div className="mt-2 flex items-center gap-3">
            <Button size="sm" variant="outline" onClick={testWebhook}>测试推送</Button>
            {testStatus.kind !== 'idle' && (
              <span
                className={`truncate text-xs ${
                  testStatus.kind === 'done' ? 'text-green-600' : 'text-red-600'
                }`}
                title={testStatus.msg}
              >
                {testStatus.msg}
              </span>
            )}
          </div>
        </div>

        <div className="rounded-md bg-secondary/50 p-2 text-xs text-muted-foreground">日志：{logPath}</div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>关闭</Button>
          <Button size="sm" onClick={save}>保存</Button>
        </div>
        <style>{`
          .input { width:100%; height:34px; border-radius:6px; border:1px solid hsl(var(--border)); background:hsl(var(--card)); padding:0 10px; font-size:13px; outline:none; }
          .input:focus { border-color: hsl(var(--ring)); }
        `}</style>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}
