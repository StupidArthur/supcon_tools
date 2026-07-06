// 显示当前 v1 写死的"默认参数"清单。
// 跟 Python api.py / Go users.go:CreateUser 里硬编码的字段一一对应。
//
// 任何字段需要可配置化，需要补：
//   - 后端 i_list_orgs / i_list_roles 等枚举端点
//   - 前端表单控件 + 模板列
//   - CreateUser 内部去掉对应写死值

export interface FixedParam {
  name: string
  value: string
  note?: string
}

// v1 写死的所有参数（与 internal/api/users.go:CreateUser 对齐）
export const FIXED_PARAMS: FixedParam[] = [
  { name: '状态', value: '启用 (status=0)', note: '创建后立即启用' },
  { name: '类型', value: '普通用户 (type=2)', note: 'admin (type=0) 暂不支持创建' },
  { name: '组织', value: '默认组织 (orgId=1)', note: '仅支持默认组织' },
  { name: '角色', value: '默认角色 (roleId=5)', note: '枚举待确认；切换角色需补 i_list_roles' },
  { name: '性别', value: '男 (gender="1")', note: '平台枚举未核实' },
  { name: '头像', value: '无 (icon="")' },
  { name: 'code', value: '= username', note: '自动用 username 填充' },
]

interface Props {
  // "compact" = 行内（默认），"block" = 占一整行
  variant?: 'compact' | 'block'
}

export function FixedParamsInfo({ variant = 'block' }: Props) {
  const rows = FIXED_PARAMS.map((p) => (
    <tr key={p.name}>
      <td style={{ color: 'var(--fg-soft)', padding: '2px 8px 2px 0' }}>{p.name}</td>
      <td style={{ padding: '2px 8px' }}>{p.value}</td>
      {p.note && (
        <td style={{ color: 'var(--fg-faint)', fontSize: 11, padding: '2px 0' }}>{p.note}</td>
      )}
    </tr>
  ))

  return (
    <details
      style={{
        marginTop: variant === 'block' ? 12 : 0,
        padding: '8px 12px',
        background: 'var(--bg-soft)',
        borderRadius: 6,
        fontSize: 12,
        color: 'var(--fg-soft)',
      }}
    >
      <summary style={{ cursor: 'pointer', userSelect: 'none', color: 'var(--fg-soft)' }}>
        默认参数（不可选 · v1 限制）
      </summary>
      <div style={{ marginTop: 6 }}>
        <table style={{ width: 'auto', fontSize: 12 }}>
          <tbody>{rows}</tbody>
        </table>
        <div style={{ marginTop: 6, color: 'var(--fg-faint)' }}>
          ⚠️ 这些字段当前为硬编码默认值。如需修改请联系开发者更新功能（需补枚举端点 + 表单控件 + 模板列）。
        </div>
      </div>
    </details>
  )
}