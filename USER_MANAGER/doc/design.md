# USER_MANAGER 设计文档 (v0.1)

> 承接 [requirement.md](requirement.md)。v0.1 已完成实现 + 验证。
> 本文档记录设计意图 + v0.1 实际实现的差异。

---

## 1. 技术栈（最终选型）

| 层 | 选型 | 备注 |
|---|---|---|
| 桌面壳 | Wails v2 ≥ 2.10 | 实际 2.12.0，借用 WebView2 |
| 后端 | Go ≥ 1.21 | 实际 1.25.7，静态编译，单二进制 |
| 前端 | React 18 + TS 5 | dev-skill shared 推荐；**Shadcn UI 未上**（v0.1 自写 CSS Notion 风） |
| Excel 解析 + 生成 | `xuri/excelize/v2` (Go) | 解析 + 模板都在 Go 侧 |
| HTTP 客户端 | `net/http` (Go stdlib) | 无第三方依赖 |
| 日志 | `log/slog` (Go stdlib) | app.go 中关键节点记录 |
| 唯一 ID | `github.com/google/uuid` | batchID 生成 |

### 与现有栈的关系

- `alg_update/api.py`（Python）**不动**，本项目用 Go 重写等价客户端
- `alg_publish` / `alg_republish` / `data-hub-tool`（PyQt6）**不动**，本项目技术栈独立
- 端点 URL、请求/响应结构、错误码语义与 Python 版 `UserManagerAPI` **一一对应**

---

## 2. 模块拆分（最终）

### Go 后端（实际）

```
USER_MANAGER/
├── main.go                          Wails 入口 + 窗口配置
├── app.go                           App struct + Wails 绑定层
├── wails.json
├── go.mod / go.sum
│
├── internal/
│   ├── api/
│   │   ├── types.go                 User / UserDraft / PageResponse / OperationStatus / LoginConfig
│   │   ├── errors.go                ErrAPI / ErrAuthError / ErrHTTP / 鉴权码识别
│   │   ├── client.go                HTTP client + Login + token 注入 + cookies
│   │   ├── users.go                 ListUsers / GetAllUsers / CreateUser / ResetPassword
│   │   └── *_test.go                8 个测试
│   │
│   ├── batch/
│   │   ├── users.go                 BatchCreateUsers（errgroup.SetLimit 并发 + 进度回调）
│   │   └── users_test.go            4 个测试
│   │
│   ├── excel/
│   │   ├── parser.go                xlsx → ParseResult + 行级校验
│   │   ├── template.go              WriteTemplate 生成 xlsx（含 1 行示例）
│   │   ├── parser_test.go           5 个测试（含 NoNullSlices 回归）
│   │   └── template_test.go         2 个测试
│   │
│   └── config/
│       ├── config.go                ~/.user-manager/config.json 持久化（URL+tenantId）
│       └── config_test.go           5 个测试
│
└── frontend/                        React 前端（见下）
```

**测试总数**：24/24 通过（v0.1 实际跑 `go test ./...`）

### 前端（实际）

```
frontend/src/
├── main.tsx                         React 入口
├── App.tsx                          主应用 + 状态上提 + Toast + 5 个对话框切换
├── style.css                        自写 CSS Token（Notion 风），无 Tailwind
│
├── lib/
│   └── api.ts                       Wails 绑定封装（业务组件只引这个）
│
└── components/
    ├── LoginDialog.tsx              登录对话框（带 URL/Tenant/Username 默认值）
    ├── UserList.tsx                 用户列表（表格 + 每行 [重置密码] secondary 按钮）
    ├── CreateUserDialog.tsx         单条创建对话框（含 FixedParamsInfo）
    ├── ResetPasswordDialog.tsx      重置密码对话框
    ├── BatchCreateDialog.tsx        批量对话框：选文件 + 模板下载 + 摘要视图（480px 宽）
    ├── BatchProgressTable.tsx       批量进度表（实时事件订阅）
    └── FixedParamsInfo.tsx          折叠块，列出 7 个硬编码默认参数
```

### 分层原则

| 文件 | 职责 | 依赖 |
|---|---|---|
| `main.go` | Wails 启动 | app.go |
| `app.go` | 绑定层，转发到核心逻辑 | 核心逻辑 + Wails runtime |
| `internal/api/*.go` | HTTP 调用 + 平台端点 | net/http, encoding/json |
| `internal/batch/*.go` | 批量并发 + 进度 | api, runtime.EventsEmit |
| `internal/excel/*.go` | xlsx 解析 + 模板生成 | excelize |
| `internal/config/*.go` | 配置持久化 | os, encoding/json |
| `frontend/src/lib/api.ts` | Wails 绑定统一封装 | Wails 生成的 bindings |
| `frontend/src/components/*.tsx` | UI 展示 + 交互回调 | api.ts |

**关键约束**：核心逻辑文件（`internal/*/*.go`）**不 import Wails**，保证可独立 `go test`。

---

## 3. 修改逻辑

### 3.1 Go 端绑定方法（实际 13 个）

```go
// app.go

// 登录态
func (a *App) Login(url, username, password, tenantID string) *api.OperationStatus
func (a *App) Logout() bool
func (a *App) IsLoggedIn() bool
func (a *App) LoadLoginConfig() *api.LoginConfig
func (a *App) SaveLoginConfig(url, tenantID string) bool

// 用户列表
func (a *App) ListUsers(page, pageSize int, keyword string) *api.PageResponse
func (a *App) GetAllUsers(keyword string) []api.User  // 自动翻页

// 单条
func (a *App) CreateUser(input api.UserDraft) *api.OperationStatus
func (a *App) ResetPassword(userID int64, newPassword string) *api.OperationStatus

// 批量
func (a *App) PickExcelFile() string                          // 文件选择框
func (a *App) DownloadBatchTemplate() string                  // 模板下载（SaveFileDialog）
func (a *App) ParseExcelFile(path string) *excelparse.ParseResult
func (a *App) BatchCreateUsers(drafts []api.UserDraft, concurrency int) string  // 返回 batchId
func (a *App) CancelBatch(batchID string) bool
```

### 3.2 前端组件树（实际）

```
App.tsx
├── Toast 区（右下角）
└── Toolbar（搜索 + 新建 + 批量 + 登出 + 水印）
├── UserList（表格）
└── 弹窗（条件渲染）
    ├── LoginDialog        未登录时弹
    ├── CreateUserDialog   + 新建 按钮
    ├── ResetPasswordDialog 行内 [重置密码]
    ├── BatchCreateDialog  批量 按钮
    └── BatchProgressTable batchId 不为空时弹（直到 finished）
```

### 3.3 关键流程

#### 登录（v0.1 实测 OK）

```
[前端]                                [Go]                                [平台]
  LoginDialog（预填 URL/Tenant/Username）
  apiClient.login(url, user, pass, tenant)
        │
        ▼
                                    App.Login() → api.Login()
                                      └─ POST /tpt-admin/system-manager/umsAdmin/login
                                          body: {"data": {"username":..., "password":...,
                                                  "accountType":"0", "tenantId":"A54Z32M2", ...}}
                                                                                ─────►
                                                                                ◄─────  {code: "00000", content: {token}}
                                          └─ token 存入 Client.token
                                          └─ Bearer header 自动注入后续请求
                                    OperationStatus{Code: "00000"}
        │
        ▼
  关闭 LoginDialog
  useEffect → apiClient.getAllUsers("") → 列表渲染
  SaveLoginConfig 写 ~/.user-manager/config.json
```

⚠️ **关键**：`Login` body 必须包成 `{"data": {...}}`，否则平台 A0400「用户请求参数错误」。v0.1 早期 bug 已修。

#### 批量创建（v0.1 实测 OK）

```
[前端]                                  [Go]
  BatchCreateDialog（480px 宽）
  ├─ "选择 xlsx" → apiClient.pickExcelFile() → path
  │  └─ apiClient.parseExcelFile(path) → ParseResult{users, errors}
  │     └─ 显示摘要：共 N / ✓ X / ✗ Y（行级错误折叠）
  ├─ "下载模板" → apiClient.downloadBatchTemplate() → SaveFileDialog → 写 xlsx
  └─ "开始批量创建"
        └─ apiClient.batchCreateUsers(drafts, 3) → batchId
              │
              ▼
                                      App.BatchCreateUsers()
                                        └─ go func() { batch.BatchCreateUsers(...) }()
                                            └─ errgroup.SetLimit(3) 并发
                                            └─ 每条完成 emit "batch:progress"
                                            └─ 全部完成 emit "batch:done"
        │                           EventsOn("batch:progress") 更新 BatchProgressTable
        ▼
  实时显示进度表（条数 / 成功 / 失败 / 错误原因）
  finished = true → 显示「关闭 / 刷新列表」按钮
```

事件名约定：
- `batch:progress` — 每条完成（含 `Last` 单条结果 + `Done/Failed/Total`）
- `batch:done` — 全部完成（含 `Summary` + `Results`）

#### 重置密码（v0.1 实测 OK，但有平台怪行为）

```
UserList 行 [重置密码] → ResetPasswordDialog
  apiClient.resetPassword(userID, newPwd)
        │
        ▼
                                   App.ResetPassword() → api.ResetPassword()
                                     └─ POST /umsAdmin/resetPwd
                                          body: {"data": {"id":..., "newPwd":..., "confirmPwd":...}}
                                                                       ─────►
                                                                       ◄───── {code: "00000"}
                                   OperationStatus{Code: "00000"}
        │
        ▼
  Toast "密码已重置"
  ⚠️ 旧密码仍可登（[[tpt-password-history-quirk]]）
```

### 3.4 数据契约

```go
// internal/api/types.go
type User struct { /* 14 字段，见 requirement.md §8 */ }
type UserDraft struct {
    Username string `json:"username"`   // 必填
    Password string `json:"password"`   // 必填
    NickName string `json:"nickName"`   // 必填
    Email    string `json:"email"`      // 可选（实测平台接受空）
    Phone    string `json:"phone"`      // 可选（实测平台接受空）
}
type LoginConfig struct {
    URL      string `json:"url"`
    TenantID string `json:"tenantId"`
}
```

### 3.5 Excel Schema（v0.1 实测）

**模板生成位置**：Go 侧 `internal/excel/template.go:WriteTemplate`
**触发方式**：`BatchCreateDialog` "下载模板"按钮 → `App.DownloadBatchTemplate()` → SaveFileDialog

列定义：

| 列 | 字段 | 必填 | 示例（Go 侧硬编码） |
|---|---|---|---|
| A | username | ✓ | zhangsan |
| B | password | ✓ | Init@2026 |
| C | nickName | ✓ | 张三 |
| D | email |   | zhangsan@example.com |
| E | phone |   | 13800138000 |

**为什么不打包二进制到仓库**：Go 现场生成，单一信息源（schema 改了模板自动跟上），仓库不用管 xlsx diff。

**解析端校验**：
- 必填：username / password / nickName
- email 非空时必须含 @
- phone 非空时长度 ≥ 6

**空字段安全**：
- 缺列 → 列为 -1 哨兵（不会误指向第一列）
- 空行 → cell 返回 ""，不进 draft

---

## 4. 技术路线（分歧 + 落地推荐）

### 分歧 1：Excel 解析在哪一侧？ → Go 侧 ✅

落地：`internal/excel/parser.go` + `template.go`。前端零解析依赖。

### 分歧 2：批量进度推送 → Wails Events ✅

落地：`runtime.EventsEmit` + 前端 `EventsOn`。约定 `batch:progress` / `batch:done`。

### 分歧 3：登录态保存 → 内存 + URL/TenantId 持久化 ✅

落地：`internal/config` 读/写 `~/.user-manager/config.json`（仅 URL+Tenant）。

### 分歧 4：批量并发上限 → 默认 3，上限 20 ✅

落地：`internal/batch/users.go:DefaultConcurrency = 3, MaxConcurrency = 20`。

### 分歧 5（v0.1 新增）：模板怎么给用户？ → Go 现场生成 ✅

走 `SaveFileDialog` 让用户选保存位置，`excelize.NewFile()` 在内存建表，writer 写入用户选的文件。

---

## 5. 横切规则检查

### 5.1 runtime-safety ✅

| 项 | 落地 |
|---|---|
| **增量持久化** | 批量每完成一条 emit 进度事件 + 写入 `Batch.Results`（内存）。v2 TODO 升级为落盘恢复 |
| **底层日志** | `slog.Default()` 记录：login / list_algorithms / create / batch_start/progress(每 N)/done / cancel / 异常 |
| **崩溃恢复** | v1 不实现 |

### 5.2 llm-integration ❌ 不适用

### 5.3 dev-skill 设计评审自检

- ✅ 模块职责单一
- ✅ 接口清晰（`Get/List/Pick/Create/Reset/Cancel/Batch` 命名一致）
- ✅ 无冗余兼容
- ✅ **关键修复**：Go nil slice → JSON null → 前端白屏，已加回归测试 `TestParseFile_NoNullSlices`

---

## 6. 实施清单（v0.1 完成状态）

| # | 步骤 | 状态 | 备注 |
|---|---|---|---|
| 1 | 环境准备（Go 1.25 / Wails 2.12 / Node 24） | ✅ | `wails doctor` 全绿 |
| 2 | wails init + dir flatten | ✅ | 模板 user-manager/ 拍平到 USER_MANAGER/ |
| 3 | Go 核心逻辑（api + batch + excel + config） | ✅ | 24 测试通过 |
| 4 | Wails 绑定层（app.go 13 个方法） | ✅ | |
| 5 | main.go + wails.json 配置 | ✅ | 1180×780, MinWidth 920, 中文标题 |
| 6 | 前端 App.tsx + 7 个组件 | ✅ | Shadcn 跳过，自写 CSS |
| 7 | xlsx 模板下载 | ✅ | Go 侧生成 + SaveFileDialog |
| 8 | FixedParamsInfo（透明化硬编码） | ✅ | 7 行折叠表 |
| 9 | 启动登录默认值 | ✅ | URL/Tenant/Username 预填 |
| 10 | JS null-safety（防白屏） | ✅ | `?.` 链 + Go 端 slice init |
| 11 | 按钮样式 + 水印 | ✅ | 重置密码/登出 secondary；"v0.1 designed by @yuzechao" |
| 12 | wails build | ✅ | 13 MB（≤15 MB 红线） |

---

## 7. v0.1 已知偏差（vs 原设计）

| 项 | 原设计 | v0.1 实际 | 原因 |
|---|---|---|---|
| Shadcn UI | 必须用 | 自写 CSS 替代 | shadcn init 交互式 CLI 重型，v0.1 跳过 |
| 批量对话框 | 完整可编辑表格（5 列 input × N 行） | 摘要视图 + 行级错误折叠 | 用户反馈"界面精简一点" |
| 启动登录值 | 无 | URL/Tenant/Username 预填 | 提升 demo 体验 |
| 默认参数展示 | 无 | FixedParamsInfo 折叠块 | 透明化硬编码值 |
| 模板下载 | 无 | Go 现场生成 + SaveFileDialog | 解决"没模板用户不会填" |
| 水印 | 无 | "v0.1 designed by @yuzechao" | 工具栏右侧 |
| 按钮样式 | 重置密码/登出 = ghost | secondary | 用户反馈 |

---

## 8. 历史 bug 修复

| 时间 | 问题 | 根因 | 修复 |
|---|---|---|---|
| v0.1 early | Login A0400「用户请求参数错误」 | body 漏 `{"data":...}` wrapper | `client.go:Login()` 包成 `{"data":{...}}` |
| v0.1 early | 上传 xlsx 后白屏 | Go nil slice → JSON null → 前端 `.length` 抛错 | `parser.go` slice init；前端加 `?.` |

---

## 9. 待跟进（不影响 v1）

- UPDATE / DELETE 端点（需用户提供 curl 样本）
- `i_list_orgs` / `i_list_roles`（组织 / 角色下拉框，让 FixedParamsInfo 7 个硬编码值可配置）
- 普通用户改自己密码端点（独立 /changePwd 端点）
- 批量任务崩溃恢复（v2 加 batch state file）
- 平台密码 reset 不失效问题上报（[[tpt-password-history-quirk]]）
- Shadcn UI 接入（提升视觉一致性）
- 单元测试覆盖率报告（v0.1 未配）

---

## 10. 关联文档

- [requirement.md](requirement.md) — 需求文档
- 平台行为备忘：[[tpt-password-history-quirk]], [[tpt-ums-endpoint-namespace]]
- 测试环境：[[tpt-supcon-saas-env]]
