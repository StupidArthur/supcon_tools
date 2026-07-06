import { useState } from 'react'
import { FixedParamsInfo } from './FixedParamsInfo'

interface Props {
  onSubmit: (input: { username: string; password: string; nickName: string; email: string; phone: string }) => void
  onClose: () => void
}

export function CreateUserDialog({ onSubmit, onClose }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [nickName, setNickName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')

  function submit() {
    if (!username || !password || !nickName) return
    onSubmit({ username, password, nickName, email, phone })
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog">
        <h2>新建用户</h2>
        <div className="field">
          <label>用户名 *</label>
          <input style={{ width: '100%' }} value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label>初始密码 *</label>
          <input type="password" style={{ width: '100%' }} value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label>昵称 *</label>
          <input style={{ width: '100%' }} value={nickName} onChange={(e) => setNickName(e.target.value)} />
        </div>
        <div className="field">
          <label>邮箱</label>
          <input style={{ width: '100%' }} value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label>手机</label>
          <input style={{ width: '100%' }} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>

        <FixedParamsInfo variant="block" />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="secondary" onClick={onClose}>取消</button>
          <button className="primary" onClick={submit} disabled={!username || !password || !nickName}>
            创建
          </button>
        </div>
      </div>
    </div>
  )
}
