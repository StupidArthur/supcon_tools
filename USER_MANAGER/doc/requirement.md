# USER_MANAGER 需求文档 (v0.1)

> 本文档 + [design.md](design.md) 是 v0.1 的最终交付。
> v0.1 已构建并实测过：登录 / 列用户 / 单建 / 重置密码 / 批量创建（xlsx）全链路通。

## 1. 需求复述

在 `USER_MANAGER/` 目录新增一个基于 **Wails v2 + Go + React 18** 的桌面 GUI 工具，调用 TPT 后台用户管理 API（基于现有 `UserManagerAPI` 等价语义在 Go 端重写），核心功能：

- **登录**：URL / 账号 / 密码 / 租户 ID 输入 → 走 `/tpt-admin/system-manager/umsAdmin/login`
- **用户列表**：分页浏览 + 关键字搜索 + 刷新（调 `/xpt-system/api/system-manager/umsAdmin/listByOrgId`）
- **单条创建**：表单输入 username / password / nickName / email（可选）/ phone（可选） → 调 `/xpt-system/api/system-manager/umsAdmin`
- **单条重置密码**：选用户 → 输入新密码 → 调 `/xpt-system/api/system-manager/umsAdmin/resetPwd`
- **批量创建**：
  - 从对话框下载模板（Go 侧现场生成 .xlsx，含 1 行示例）
  - 选 .xlsx → 解析 → 摘要视图（总数 / 有效 / 无效）+ 行级错误折叠
  - 确认 → 并发 N 次 create → 实时进度表 + 事件订阅

## 2. 边界识别

| 涉及 | 不涉及 |
|---|---|
| `USER_MANAGER/` 目录新建 Go 项目 + React 前端 | 改动 `common/api.py`（Python 链路） |
| 新增 `go.mod` / `wails.json` / `frontend/` / `build/` | 服务化 / 多用户 / 权限模型 |
| TPT 域用户管理 5 个端点（login/list/create/resetPwd/batch-client） | 普通用户改自己密码（另一端点） |
| 单进程桌面工具 | UPDATE / DELETE / 角色管理 / 组织管理（v1 不带） |
| 默认参数展示 + 模板下载 + 启动默认值 | 批量上传后的逐行编辑（v1 不带） |

## 3. 影响面

- ✅ 已有的 Python `api.py` 不动 — Go 端按相同契约重写
- ✅ Go 端新增 `internal/{api,batch,excel,config}/` 包
- ⚠️ 批量创建如果并发 > 5 会触发平台限流风险，默认 3，可配上限 20
- ⚠️ Wails 事件机制（Go → JS）需要规划进度回调
- ⚠️ Go nil slice 序列化成 null 的坑（已修，见 §6 历史 bug）

## 4. 需求合并空间

- 单条创建表单 ↔ 批量创建预览，都是 `UserDraft[]` → `create` 转换
- 登录态在 Go 端 `App` 结构体上，整个会话内复用
- **xlsx 模板和 xlsx 解析共用同一份 schema**（`username` / `password` / `nickName` / `email` / `phone` 列定义都在 `internal/excel` 里）

## 5. 技术栈（已确认）

| 项 | 选型 | 来源 |
|---|---|---|
| 桌面壳 | Wails v2 ≥ 2.10 | dev-skill gui-tool 强制 |
| 后端 | Go ≥ 1.21 | dev-skill gui-tool 强制 |
| 前端 | React 18 + TS 5 | dev-skill shared 推荐 |
| Excel | Go `xuri/excelize/v2` | 与 Go 重写 API 对齐 |
| 登录态 | 内存 + 仅持久化 URL/租户（不存密码） | 安全默认 |

**妥协**：原计划用 Shadcn UI，但 shadcn init 是交互式 CLI 重型，v0.1 跳过；前端用自写 CSS + Notion 风格 token 替代。后续可补（见 §7）。

## 6. 默认决策（已锁）

| 项 | 默认 |
|---|---|
| 前端框架 | React 18 + TS 5（自写 CSS，暂未上 Shadcn） |
| Excel 解析侧 | Go 侧 |
| Excel 模板生成 | Go 侧现场生成（不打包二进制） |
| 登录态持久化 | URL + 租户 ID（不存密码） |
| 启动登录默认值 | URL=`https://supcontpt.supcon.com` / Tenant=`A54Z32M2` / Username=`admin`（密码留空） |
| 窗口 | 单窗口 1180×780 |
| 主题 | 跟随系统 / 自写 CSS 浅色 Notion 风 |
| 批量并发 | 默认 3，上限 20 |
| 邮箱 / 手机 | 可选（平台实测接受空字符串） |

## 7. v0.1 已知偏差（vs 原设计）

| 项 | 原设计 | v0.1 实现 | 备注 |
|---|---|---|---|
| 批量对话框 | 完整可编辑表格（5 列 input × N 行） | 摘要视图（总数/有效/无效）+ 行级错误折叠 | 用户反馈"界面精简一点" |
| Shadcn UI | 必须用 | 自写 CSS 替代 | 后续补 |
| 启动默认值 | 无 | URL/Tenant/Username 预填 | 提升 demo 体验 |
| 默认参数展示 | 无 | `FixedParamsInfo` 折叠块 | 透明化硬编码值 |
| 模板下载 | 无 | Go 侧生成 + SaveFileDialog | 解决"没模板用户不会填"问题 |
| 水印 | 无 | "v0.1 designed by @yuzechao" | 工具栏右侧 |
| 按钮样式 | 重置密码 / 登出 = `ghost` | 改为 `secondary` | 用户反馈 |

## 8. 数据契约（从 Python 实测响应锁定）

```go
type User struct {
    ID         int64  `json:"id"`
    Username   string `json:"username"`
    Code       string `json:"code"`
    NickName   string `json:"nickName"`
    Email      string `json:"email"`
    Phone      string `json:"phone"`
    Gender     int    `json:"gender"`
    Status     int    `json:"status"`
    Type       int    `json:"type"`
    TenantID   string `json:"tenantId"`
    DelFlag    int    `json:"delFlag"`
    CreateTime string `json:"createTime"`
    LoginTime  string `json:"loginTime"`
    UpdateTime string `json:"updateTime"`
}
```

`UserDraft` (创建输入) — 5 字段：username / password / nickName / email / phone，email/phone 可空。

## 9. 历史 bug（已修复，留档）

| 时间 | 问题 | 修复 |
|---|---|---|
| v0.1 early | Login body 漏 `{"data": ...}` wrapper，平台报 A0400「用户请求参数错误」 | `internal/api/client.go:Login()` 把 body 包成 `{"data": {...}}` |
| v0.1 early | Go nil slice → JSON null → 前端 `.length` 抛错 → 上传 xlsx 后白屏 | `internal/excel/parser.go` 把所有 slice 初始化为 `[]T{}`；前端加 `?.` 链防 null |

回归测试：`internal/excel/parser_test.go:TestParseFile_NoNullSlices` 锁住。

## 10. 测试账号（v0.1 调试用，清理阶段会删）

- `__probe_i_create_user__`
- `__verify_i_create_user__` (id=474357)
- `__probe_empty_fields__`

## 11. 待跟进（不影响 v1 设计）

- UPDATE / DELETE 端点（待用户给样本）
- `i_list_orgs` / `i_list_roles`（组织 / 角色下拉框，让 `FixedParamsInfo` 里那 7 个硬编码值可配置）
- 普通用户改自己密码端点
- 平台 reset 后旧密码不失效的合规问题（已记录 [[tpt-password-history-quirk]]）
- 批量任务崩溃恢复（v2）
- Shadcn UI 接入（提升视觉一致性）
- 单元测试覆盖率报告（v0.1 未配）

## 12. 关联文档

- [design.md](design.md) — 设计文档（含模块拆分 / 实施清单）
- 平台行为备忘：[[tpt-password-history-quirk]], [[tpt-ums-endpoint-namespace]]
- 测试环境：[[tpt-supcon-saas-env]]
