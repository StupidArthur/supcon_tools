import type { User } from '../lib/api'

interface Props {
  users: User[]
  onReset: (user: User) => void
}

export function UserList({ users, onReset }: Props) {
  if (users.length === 0) {
    return <div style={{ padding: 24, color: 'var(--fg-faint)', textAlign: 'center' }}>暂无用户</div>
  }
  return (
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>用户名</th>
          <th>昵称</th>
          <th>邮箱</th>
          <th>手机</th>
          <th>类型</th>
          <th>状态</th>
          <th>最后登录</th>
          <th style={{ width: 120 }}>操作</th>
        </tr>
      </thead>
      <tbody>
        {users.map((u) => (
          <tr key={u.id}>
            <td>{u.id}</td>
            <td>{u.username}</td>
            <td>{u.nickName}</td>
            <td>{u.email}</td>
            <td>{u.phone}</td>
            <td>{u.type === 0 ? '管理员' : '普通'}</td>
            <td>
              <span className={`tag ${u.status === 0 ? 'success' : 'error'}`}>
                {u.status === 0 ? '启用' : '禁用'}
              </span>
            </td>
            <td>{u.loginTime || '-'}</td>
            <td>
              <button className="secondary" onClick={() => onReset(u)}>重置密码</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
