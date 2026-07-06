import { useState } from 'react'
import type { User } from '../lib/api'

interface Props {
  user: User
  onSubmit: (newPassword: string) => void
  onClose: () => void
}

export function ResetPasswordDialog({ user, onSubmit, onClose }: Props) {
  const [pwd, setPwd] = useState('')

  return (
    <div className="dialog-backdrop">
      <div className="dialog">
        <h2>重置密码</h2>
        <div style={{ marginBottom: 12, color: 'var(--fg-soft)', fontSize: 13 }}>
          用户：<strong>{user.username}</strong> ({user.nickName})
        </div>
        <div className="field">
          <label>新密码</label>
          <input
            type="password"
            style={{ width: '100%' }}
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            autoFocus
          />
        </div>
        <div style={{ fontSize: 12, color: 'var(--fg-faint)', marginBottom: 12 }}>
          ⚠️ 平台行为：reset 后旧密码仍然有效（<a href="#" onClick={(e) => e.preventDefault()}>记录</a>）
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="secondary" onClick={onClose}>取消</button>
          <button className="primary" onClick={() => pwd && onSubmit(pwd)} disabled={!pwd}>
            重置
          </button>
        </div>
      </div>
    </div>
  )
}
