# USER_MANAGER 需求文档

> 用户自己实现，本文档 + [design.md](design.md) 即是最终交付。

## 1. 需求复述

在 `USER_MANAGER/` 目录新增一个基于 **Wails v2 + Go + React 18 + Shadcn UI** 的桌面 GUI 工具，调用 TPT 后台用户管理 API（基于现有 `UserManagerAPI` 等价语义在 Go 端重写），核心功能：

- **登录**：URL / 账号 / 密码 / 租户 ID 输入 → 走 `/tpt-admin/system-manager/umsAdmin/login`
- **用户列表**：分页浏览 + 关键字搜索 + 刷新（调 `/xpt-system/api/system-manager/umsAdmin/listByOrgId`）
- **单条创建**：表单输入 username / password / nickName / email / phone → 调 `/xpt-system/api/system-manager/umsAdmin`
- **单条重置密码**：选用户 → 输入新密码 → 调 `/xpt-system/api/system-manager/umsAdmin/resetPwd`
- **批量创建**：从 .xlsx 导入 → 表格预览 → 确认 → 并发调 N 次 create → 实时展示进度和结果

**用户自己实现**，本文档 + 设计文档产出后，进入实施。

## 2. 边界识别

| 涉及 | 不涉及 |
|---|---|
| `USER_MANAGER/` 目录新建 Go 项目 + React 前端 | 改动 `common/api.py`（Python 链路） |
| 新增 `go.mod` / `wails.json` / `frontend/` / `build/` | 服务化 / 多用户 / 权限模型 |
| TPT 域用户管理 5 个端点（login/list/create/resetPwd/batch-client） | 普通用户改自己密码（另一端点） |
| 单进程桌面工具 | UPDATE / DELETE / 角色管理 / 组织管理（v1 不带） |

## 3. 影响面

- ✅ 已有的 Python `api.py` 不动 — Go 端按相同契约重写
- ⚠️ Go 端新增 `internal/{api,batch,excel,config}/` 包
- ⚠️ 批量创建如果并发 > 5 会触发平台限流风险，默认 3，可配上限 20
- ⚠️ Wails 事件机制（Go → JS）需要规划进度回调

## 4. 需求合并空间

- 单条创建表单 ↔ 批量创建预览表，本质都是 `UserDraft[]` → `create` 转换，**共享同一份前端校验逻辑**（必填 / 长度 / 字符集）
- 登录态在 Go 端 `App` 结构体上，整个会话内复用，**前端不需要反复传 token**

## 5. 技术栈（已确认）

| 项 | 选型 | 来源 |
|---|---|---|
| 桌面壳 | Wails v2 ≥ 2.10 | dev-skill gui-tool 强制 |
| 后端 | Go ≥ 1.21 | dev-skill gui-tool 强制 |
| 前端 | React 18 + TS 5 + Shadcn UI + Tailwind v3 + Vite 5 | dev-skill shared 强制 |
| Excel | Go `xuri/excelize/v2` | 与 Go 重写 API 对齐 |
| 登录态 | 内存 + 仅持久化 URL/租户（不存密码） | 安全默认 |

## 6. 默认决策（已锁）

| 项 | 默认 |
|---|---|
| 前端框架 | React + Shadcn（dev-skill 强制） |
| Excel 解析侧 | Go 侧 |
| 登录态持久化 | URL + 租户 ID（不存密码） |
| 窗口 | 单窗口 1180×780 |
| 主题 | 跟随系统 |

## 7. 数据契约（从 Python 实测响应锁定）

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

## 8. 待跟进（不影响 v1 设计）

- UPDATE / DELETE 端点（待用户给样本）
- `i_list_orgs` / `i_list_roles`（组织 / 角色下拉框）
- 普通用户改自己密码端点
- 平台 reset 后旧密码不失效的合规问题（已记录 [[tpt-password-history-quirk]]）
- 批量任务崩溃恢复（v2）

## 9. 关联文档

- [design.md](design.md) — 设计文档
- 平台行为备忘：[[tpt-password-history-quirk]], [[tpt-ums-endpoint-namespace]]
