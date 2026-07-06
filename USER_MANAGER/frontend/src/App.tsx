import { useEffect, useState, useCallback } from 'react'
import { apiClient, onBatchProgress, onBatchDone, type User, type ParsedRow } from './lib/api'
import { LoginDialog } from './components/LoginDialog'
import { UserList } from './components/UserList'
import { CreateUserDialog } from './components/CreateUserDialog'
import { ResetPasswordDialog } from './components/ResetPasswordDialog'
import { BatchCreateDialog } from './components/BatchCreateDialog'
import { BatchProgressTable, type BatchResult } from './components/BatchProgressTable'

interface Toast {
  id: number
  msg: string
  kind: 'info' | 'success' | 'error'
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false)
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [toasts, setToasts] = useState<Toast[]>([])

  const [showLogin, setShowLogin] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showBatch, setShowBatch] = useState(false)
  const [resetUser, setResetUser] = useState<User | null>(null)
  const [batchProgress, setBatchProgress] = useState<{
    batchId: string | null
    total: number
    done: number
    failed: number
    results: BatchResult[]
    finished: boolean
  }>({ batchId: null, total: 0, done: 0, failed: 0, results: [], finished: false })

  const toast = useCallback((msg: string, kind: Toast['kind'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, msg, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500)
  }, [])

  const refresh = useCallback(async (kw?: string) => {
    setLoading(true)
    try {
      const list = await apiClient.getAllUsers(kw ?? keyword)
      setUsers(list)
    } catch (e: any) {
      toast(String(e), 'error')
    } finally {
      setLoading(false)
    }
  }, [keyword, toast])

  // 启动：检查登录态 + 拉 URL/TenantID 回填
  useEffect(() => {
    (async () => {
      const ok = await apiClient.isLoggedIn()
      if (ok) {
        setLoggedIn(true)
        refresh('')
      } else {
        setShowLogin(true)
      }
    })()
  }, [refresh])

  // 订阅批量进度事件
  useEffect(() => {
    const off1 = onBatchProgress((batchId, p) => {
      setBatchProgress((s) =>
        s.batchId === batchId
          ? { ...s, total: p.total, done: p.done, failed: p.failed, results: p.last ? [...s.results, p.last] : s.results, finished: p.finished }
          : s
      )
    })
    const off2 = onBatchDone((batchId, summary, results) => {
      setBatchProgress((s) =>
        s.batchId === batchId
          ? { batchId, total: summary.total, done: summary.done, failed: summary.failed, results, finished: true }
          : s
      )
    })
    return () => { off1(); off2() }
  }, [])

  async function handleLogin(url: string, user: string, pass: string, tenant: string) {
    const r = await apiClient.login(url, user, pass, tenant)
    if (r.code === '00000') {
      setLoggedIn(true)
      setShowLogin(false)
      await apiClient.saveLoginConfig(url, tenant)
      toast('登录成功', 'success')
      refresh('')
    } else {
      toast(`登录失败: [${r.code}] ${r.msg}`, 'error')
    }
  }

  async function handleLogout() {
    await apiClient.logout()
    setLoggedIn(false)
    setUsers([])
    setShowLogin(true)
  }

  async function handleCreate(input: { username: string; password: string; nickName: string; email: string; phone: string }) {
    const r = await apiClient.createUser(input)
    if (r.code === '00000') {
      toast(`创建成功: ${input.username}`, 'success')
      setShowCreate(false)
      refresh()
    } else {
      toast(`创建失败: [${r.code}] ${r.msg}`, 'error')
    }
  }

  async function handleReset(userID: number, newPwd: string) {
    const r = await apiClient.resetPassword(userID, newPwd)
    if (r.code === '00000') {
      toast('密码已重置（旧密码仍可能有效 — 平台行为）', 'success')
      setResetUser(null)
    } else {
      toast(`重置失败: [${r.code}] ${r.msg}`, 'error')
    }
  }

  async function handleBatchStart(rows: ParsedRow[], concurrency: number) {
    setShowBatch(false)
    const drafts = rows
      .filter((r) => r.errors.length === 0)
      .map((r) => ({
        username: r.draft.username,
        password: r.draft.password,
        nickName: r.draft.nickName,
        email: r.draft.email,
        phone: r.draft.phone,
      }))
    if (drafts.length === 0) {
      toast('没有可创建的有效行', 'error')
      return
    }
    const batchId = await apiClient.batchCreateUsers(drafts, concurrency)
    if (!batchId) {
      toast('启动批量任务失败（未登录？）', 'error')
      return
    }
    setBatchProgress({ batchId, total: drafts.length, done: 0, failed: 0, results: [], finished: false })
    toast(`批量任务已启动，共 ${drafts.length} 条`, 'info')
  }

  async function handleBatchCancel() {
    if (!batchProgress.batchId) return
    await apiClient.cancelBatch(batchProgress.batchId)
    toast('已请求取消', 'info')
  }

  const batchVisible = batchProgress.batchId !== null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        <input
          placeholder="搜索 username / nickName / phone / email"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') refresh() }}
          style={{ width: 320 }}
        />
        <button className="secondary" onClick={() => refresh()} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
        <div style={{ flex: 1 }} />
        <button className="secondary" onClick={() => setShowCreate(true)} disabled={!loggedIn}>+ 新建用户</button>
        <button className="primary" onClick={() => setShowBatch(true)} disabled={!loggedIn}>批量创建</button>
        <button className="secondary" onClick={handleLogout} disabled={!loggedIn}>登出</button>
        <span style={{ marginLeft: 12, fontSize: 11, color: 'var(--fg-faint)' }}>
          v0.1 &nbsp;designed by @yuzechao
        </span>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        <UserList users={users} onReset={(u) => setResetUser(u)} />
      </div>

      {showLogin && <LoginDialog onSubmit={handleLogin} />}
      {showCreate && <CreateUserDialog onSubmit={handleCreate} onClose={() => setShowCreate(false)} />}
      {resetUser && (
        <ResetPasswordDialog
          user={resetUser}
          onSubmit={(pwd) => handleReset(resetUser.id, pwd)}
          onClose={() => setResetUser(null)}
        />
      )}
      {showBatch && <BatchCreateDialog onStart={handleBatchStart} onClose={() => setShowBatch(false)} onMessage={toast} />}
      {batchVisible && (
        <BatchProgressTable
          {...batchProgress}
          onCancel={handleBatchCancel}
          onClose={() => setBatchProgress({ batchId: null, total: 0, done: 0, failed: 0, results: [], finished: false })}
          onRefreshList={() => refresh()}
        />
      )}

      <div className="toast-area">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>
        ))}
      </div>
    </div>
  )
}
