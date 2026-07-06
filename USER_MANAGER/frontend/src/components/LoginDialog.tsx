import { useEffect, useState } from 'react'
import { apiClient } from '../lib/api'

// 默认预填值（开发环境常用配置；用户可改）
const DEFAULT_URL = 'https://supcontpt.supcon.com'
const DEFAULT_TENANT = 'A54Z32M2'
const DEFAULT_USERNAME = 'admin'

interface Props {
  onSubmit: (url: string, user: string, pass: string, tenant: string) => void
}

export function LoginDialog({ onSubmit }: Props) {
  const [url, setUrl] = useState(DEFAULT_URL)
  const [user, setUser] = useState(DEFAULT_USERNAME)
  const [pass, setPass] = useState('')
  const [tenant, setTenant] = useState(DEFAULT_TENANT)
  const [busy, setBusy] = useState(false)

  // 启动时回填 URL/TenantID（如果有 config.json 覆盖默认值）
  useEffect(() => {
    apiClient.loadLoginConfig().then((cfg) => {
      if (cfg.url) setUrl(cfg.url)
      if (cfg.tenantId) setTenant(cfg.tenantId)
      // 用户名 / 密码不存，所以不覆盖默认 username
    })
  }, [])

  function submit() {
    if (!url || !user || !pass) return
    setBusy(true)
    // 注意：父组件的 onSubmit 是 async，但这里不 await — 让 toast 在父组件处理
    onSubmit(url, user, pass, tenant)
    // 给个短暂的 busy 防双击；父组件成功会 setShowLogin(false)
    setTimeout(() => setBusy(false), 1500)
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog">
        <h2>登录 TPT 后台</h2>
        <div className="field">
          <label>服务器 URL</label>
          <input
            style={{ width: '100%' }}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://supcontpt.supcon.com"
          />
        </div>
        <div className="field">
          <label>账号</label>
          <input style={{ width: '100%' }} value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className="field">
          <label>密码</label>
          <input type="password" style={{ width: '100%' }} value={pass} onChange={(e) => setPass(e.target.value)} />
        </div>
        <div className="field">
          <label>租户 ID（HTTPS 多租户必填，HTTP 留空）</label>
          <input
            style={{ width: '100%' }}
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
            placeholder="例如 A54Z32M2"
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="primary" onClick={submit} disabled={busy || !url || !user || !pass}>
            {busy ? '登录中…' : '登录'}
          </button>
        </div>
      </div>
    </div>
  )
}
