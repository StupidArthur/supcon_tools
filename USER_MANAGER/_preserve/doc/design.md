# USER_MANAGER 设计文档

> 承接 [requirement.md](requirement.md)。按 dev-skill 设计阶段产出。
> 用户自己实现，本文档即是最终交付。

---

## 1. 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 桌面壳 | Wails v2 ≥ 2.10 | 借用 WebView2，体积 ~11MB |
| 后端 | Go ≥ 1.21 | 静态编译，单二进制 |
| 前端 | React 18 + TS 5 + Shadcn UI + Tailwind v3 + Vite 5 + Radix UI + lucide-react | dev-skill 强制约束 |
| Excel 解析 | `xuri/excelize/v2` (Go) | 与"Go 重写 API"对齐，前端零解析负担 |
| HTTP 客户端 | `net/http` (Go stdlib) | 无第三方依赖 |
| 日志 | `log/slog` (Go stdlib, Go 1.21+) | 关键业务节点 |

### 与现有栈的关系

- `alg_update/api.py`（Python）**不动**，本项目用 Go 重写等价客户端
- `alg_publish` / `alg_republish` / `data-hub-tool`（PyQt6）**不动**，本项目技术栈独立
- 端点 URL、请求/响应结构、错误码语义与 Python 版 `UserManagerAPI` **一一对应**

---

## 2. 模块拆分

### Go 后端

```
USER_MANAGER/
├── main.go                          Wails 入口 + 窗口配置
├── app.go                           App struct + 暴露给前端的方法（绑定层）
├── wails.json                       Wails 配置
├── go.mod / go.sum
│
├── internal/
│   ├── api/
│   │   ├── client.go                HTTP client、登录、token 注入
│   │   ├── client_test.go
│   │   ├── users.go                 ListUsers / CreateUser / ResetPassword
│   │   ├── users_test.go
│   │   ├── types.go                 User / UserDraft / API 响应类型
│   │   └── errors.go                ApiError、鉴权码识别（A0230/A0201/...）
│   │
│   ├── batch/
│   │   ├── users.go                 BatchCreateUsers（并发、进度事件、取消）
│   │   └── users_test.go
│   │
│   ├── excel/
│   │   ├── parser.go                xlsx → []UserDraft + 校验
│   │   └── parser_test.go
│   │
│   └── config/
│       ├── config.go                URL / 租户 ID 持久化（不存密码）
│       └── config_test.go
│
└── frontend/                        React 前端（见下）
```

### 前端

```
frontend/src/
├── main.tsx                         React 入口
├── App.tsx                          主应用（状态上提 + ToastProvider）
├── style.css                        Tailwind + 设计 Token
│
├── lib/
│   ├── api.ts                       Wails 绑定封装（业务组件只引这个）
│   ├── types.ts                     业务类型重导出
│   └── utils.ts                     cn() 等
│
└── components/
    ├── ui/                          Shadcn 组件（复制即用，不改核心）
    │   ├── button.tsx
    │   ├── dialog.tsx
    │   ├── input.tsx
    │   ├── table.tsx
    │   ├── toast.tsx
    │   └── ...
    ├── LoginDialog.tsx              登录对话框
    ├── UserList.tsx                 用户列表（表格 + 分页 + 搜索）
    ├── CreateUserDialog.tsx         单条创建对话框
    ├── ResetPasswordDialog.tsx      重置密码对话框
    ├── BatchCreateDialog.tsx        批量创建对话框（导入 + 预览 + 提交）
    ├── BatchProgressTable.tsx       批量进度表（实时更新）
    └── ConfirmDialog.tsx            通用确认
```

### 分层原则

| 文件 | 职责 | 依赖 |
|---|---|---|
| `main.go` | Wails 启动 | app.go |
| `app.go` | 绑定层，转发到核心逻辑 | 核心逻辑 + Wails runtime |
| `internal/api/*.go` | HTTP 调用 + 平台端点 | net/http, encoding/json |
| `internal/batch/*.go` | 批量并发 + 进度 | api, runtime.EventsEmit |
| `internal/excel/*.go` | xlsx 解析 + 校验 | excelize |
| `frontend/src/lib/api.ts` | Wails 绑定统一封装 | Wails 生成的 bindings |
| `frontend/src/components/*.tsx` | UI 展示 + 交互回调 | api.ts |

**关键约束**：核心逻辑文件（`internal/*/*.go`）**不 import Wails**，保证可独立 `go test`。

---

## 3. 修改逻辑

### 3.1 Go 端绑定方法（Wails → 前端）

```go
// app.go

// 登录
type LoginResult struct {
    Success bool   `json:"success"`
    Error   string `json:"error"`
    UserID  int64  `json:"userId"`
    Token   string `json:"token"`  // 仅用于前端显示"已登录"，不暴露给 UI
}
func (a *App) Login(url, username, password, tenantId string) LoginResult

// 用户列表
type UserListResult struct {
    Success bool   `json:"success"`
    Error   string `json:"error"`
    Total   int64  `json:"total"`
    Users   []User `json:"users"`
}
func (a *App) ListUsers(page, pageSize int, keyword string) UserListResult
func (a *App) GetAllUsers(keyword string) UserListResult  // 自动翻页，缓存

// 单条创建
type CreateUserInput struct {
    Username string `json:"username"`
    Password string `json:"password"`
    NickName string `json:"nickName"`
    Email    string `json:"email"`
    Phone    string `json:"phone"`
    // orgIds / roleIds 写死 [1] / "5"，v1 不暴露
}
type OperationResult struct {
    Success bool   `json:"success"`
    Error   string `json:"error"`
    Code    string `json:"code"`    // 平台返回码
    Msg     string `json:"msg"`     // 平台返回消息
}
func (a *App) CreateUser(input CreateUserInput) OperationResult

// 重置密码
func (a *App) ResetPassword(userId int64, newPassword string) OperationResult

// 批量创建
func (a *App) PickExcelFile() string                          // 文件选择框
func (a *App) ParseExcelFile(path string) ParseResult         // 解析 + 校验
func (a *App) BatchCreateUsers(users []CreateUserInput) string // 返回 batchId
func (a *App) CancelBatch(batchId string) bool
func (a *App) GetBatchProgress(batchId string) BatchProgress   // 轮询备用

// 登录态
func (a *App) IsLoggedIn() bool
func (a *App) Logout() bool
func (a *App) SaveLoginConfig(url, tenantId string) bool      // 持久化 URL+租户
func (a *App) LoadLoginConfig() LoginConfig                   // 启动时读
```

### 3.2 前端组件树

```
App.tsx
├── ToastProvider
├── LoginDialog                  未登录时弹出
└── (已登录后)
    ├── Sidebar (后续可加)
    └── Main
        ├── TopBar: 搜索框 + 新建按钮 + 批量按钮 + 登出
        ├── UserList: 表格（id/username/nickName/email/phone/status）
        │   └── 每行: [重置密码] 按钮
        ├── CreateUserDialog: 单条表单
        └── BatchCreateDialog: xlsx 导入 + 预览 + 提交
            └── BatchProgressTable: 实时进度
```

### 3.3 关键流程

#### 登录

```
[前端]                                [Go]                                [平台]
  LoginDialog 填表
  api.login(url, user, pwd, tenant)
        │
        ▼
                                    App.Login()
                                      └─ api.Login()
                                          └─ POST /tpt-admin/system-manager/umsAdmin/login
                                                                                ─────►
                                                                                ◄─────
                                          └─ token 存入 App.token
                                          └─ cookies 设 TptSaasUserTenantryId / tenant-id
                                    LoginResult{Success: true}
        │
        ▼
  关闭 LoginDialog
  触发 useEffect → api.listUsers(1, 10, "")
```

#### 批量创建

```
[前端]                                 [Go]
  BatchCreateDialog
  api.pickExcelFile() → "C:/users.xlsx"
  api.parseExcelFile(path)
        │
        ▼
                                     ParseResult{Users: [...]}
  表格预览 + 编辑
  用户点"开始批量创建"
  api.batchCreateUsers(users) → batchId
        │
        ▼
                                     App.BatchCreateUsers()
                                       └─ 创建 Batch{BatchID, Done, Failed, Total, Results}
                                       └─ go func() { ... 并发 N 个 create ... }()
                                       └─ 每完成一条: runtime.EventsEmit(ctx, "batch:progress", ...)
        │                             每个 goroutine 调 api.CreateUser() 一次
        │                             错误捕获到 Result.Error，不 panic
        ▼
  订阅 "batch:progress" 事件
  实时更新 BatchProgressTable
  全部完成事件 "batch:done"
  显示结果 + 导出按钮
```

并发度：默认 3（可配置），用 `errgroup.Group + SetLimit(N)` 控制。

#### 重置密码

```
[前端]                              [Go]                              [平台]
  UserList 行 [重置密码]
  ResetPasswordDialog
  api.resetPassword(userId, newPwd)
        │
        ▼
                                   App.ResetPassword()
                                     └─ api.ResetPassword()
                                         └─ POST /umsAdmin/resetPwd
                                                                       ─────►
                                                                       ◄─────
                                   OperationResult{Success, Code: "00000"}
        │
        ▼
  Toast "密码已重置"
  注意：旧密码仍可登（[[tpt-password-history-quirk]] 平台怪行为）
```

### 3.4 数据契约

```go
// internal/api/types.go

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

type UserDraft struct {
    Username string `json:"username"`   // 必填
    Password string `json:"password"`   // 必填
    NickName string `json:"nickName"`   // 必填
    Email    string `json:"email"`      // 可选
    Phone    string `json:"phone"`      // 可选
}

type LoginConfig struct {
    URL      string `json:"url"`
    TenantID string `json:"tenantId"`
}
```

### 3.5 Excel Schema（批量创建）

`frontend/public/batch_users_template.xlsx` 提供模板，列定义：

| 列 | 字段 | 必填 | 示例 |
|---|---|---|---|
| A | username | ✓ | zhangsan |
| B | password | ✓ | InitPwd@123 |
| C | nickName | ✓ | 张三 |
| D | email |   | zhangsan@example.com |
| E | phone |   | 13800138000 |

解析失败行用红色标出，鼠标悬停看错误原因。预览阶段所有数据可编辑。

---

## 4. 技术路线（分歧 + 推荐）

### 分歧 1：Excel 解析在哪一侧？

| 方案 | 优 | 劣 |
|---|---|---|
| **Go (excelize)** | 数据流闭环，校验与后端 schema 同步；前端零依赖 | Go 端要做校验逻辑 |
| JS (SheetJS) | 前端即时反馈；无需后端往返 | 体积大（~300KB）；校验逻辑两套要同步 |

**推荐：Go 侧**。与"Go 重写 API"对齐，前端只负责展示。

### 分歧 2：批量进度推送

| 方案 | 优 | 劣 |
|---|---|---|
| **Wails Events** (`runtime.EventsEmit`) | 实时推送，无延迟；前端订阅简单 | 需前后端约定事件名 |
| 前端轮询 getBatchProgress | 实现简单 | 延迟，浪费请求 |

**推荐：Wails Events**。约定事件名：`batch:progress`（每条完成）、`batch:done`（全部完成）、`batch:error`（致命错误）。

### 分歧 3：登录态保存

| 方案 | 优 | 劣 |
|---|---|---|
| **内存 + SaveLoginConfig(URL, tenantId)** | 密码不落盘；URL/租户复用 | 重启后要重输密码 |
| 加密文件存全部 | 重启直接进 | 需密钥管理，复杂 |

**推荐：内存 + 仅持久化 URL+租户 ID**。安全与便利的平衡。

### 分歧 4：批量创建的并发上限

| 方案 | 默认值 | 理由 |
|---|---|---|
| 保守 | 3 | 防平台限流 |
| 激进 | 10 | 速度优先 |

**推荐：默认 3，可在 BatchCreateDialog 配置**（上限 20）。

---

## 5. 横切规则检查

### 5.1 runtime-safety ✅ 适用

| 项 | 落地 |
|---|---|
| **增量持久化** | 批量创建每完成一条就 emit 进度事件 + 写入 `Batch.Results` 切片（内存）。崩溃后前端结果丢失可接受，README 留 TODO 升级为落盘恢复 |
| **底层日志** | Go `log/slog` 记录：登录、列表拉取、单条创建、批量开始/进度（每 10 条）/结束/取消/异常 |
| **崩溃恢复** | v1 不实现，README TODO v2 加 batch state file |

### 5.2 llm-integration ❌ 不适用

本项目无 LLM 调用。

### 5.3 dev-skill 设计评审自检

- ✅ 模块职责单一：`api/batch/excel/config` 各管一摊
- ✅ 接口清晰：Wails 绑定方法命名 `GetXxx/ListXxx/PickXxx/CreateXxx`，前端只对 `lib/api.ts` 编程
- ✅ 无冗余兼容：v1 不写 UPDATE/DELETE，不留 deprecated 入口

---

## 6. 实施清单（用户实现时按此推进）

1. **环境**
   - 安装 Go ≥ 1.21, Node ≥ 18, Wails CLI
   - `wails doctor` 全绿

2. **脚手架**
   - `cd USER_MANAGER && wails init -n user-manager -t react-ts`
   - 删掉模板里无关文件（`frontend/src/assets/` 等）
   - 加 Shadcn: `cd frontend && npx shadcn@latest init`
   - 加 lucide-react: `npm i lucide-react`

3. **后端核心逻辑（无 Wails 依赖）**
   - 写 `internal/api/types.go`, `errors.go`
   - 写 `internal/api/client.go`：Login + token 注入 + cookies + 鉴权码识别
   - 写 `internal/api/users.go`：ListUsers / CreateUser / ResetPassword
   - 写单元测试（用 `httptest.NewServer` mock 平台）

4. **批量 + 解析**
   - 写 `internal/excel/parser.go` + 测试（用 `excelize` 打开 mock xlsx）
   - 写 `internal/batch/users.go` + 测试（mock api.CreateUser）

5. **Wails 绑定层**
   - 写 `app.go`：把核心逻辑包成 Wails 方法
   - 处理 ctx、EventsEmit 进度回调

6. **main.go + wails.json**
   - 窗口 1180×780, MinWidth 920
   - 标题"用户管理工具"
   - 背景白 `RGBA{255,255,255,1}`

7. **前端**
   - `style.css` 加 Tailwind + 设计 Token
   - `lib/api.ts` 封装 Wails bindings
   - `App.tsx` 状态上提 + ToastProvider
   - 组件顺序：LoginDialog → UserList → CreateUserDialog → ResetPasswordDialog → BatchCreateDialog + BatchProgressTable

8. **配置持久化**
   - `internal/config/config.go`：读/写 `~/.user-manager/config.json`
   - 不存密码

9. **日志**
   - `slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, ...)))`
   - 关键节点记录

10. **质量门**
    - `go test ./...` 全过
    - `wails build` 成功
    - `build/bin/user-manager.exe` ≤ 15MB
    - 手动跑通：登录 → 列表 → 单建 → 重置 → 批量导入 → 批量进度

11. **清理**
    - 删 `_probe_*.py` / `_verify_*.py` / `_probe_*.json` / `_verify_*.json`
    - 这些在 USER_MANAGER/ 留下了

---

## 7. 待跟进（不影响 v1）

- UPDATE / DELETE 端点（需用户提供 curl 样本）
- `i_list_orgs` / `i_list_roles`（组织 / 角色下拉框）
- 普通用户改自己密码端点
- 批量任务崩溃恢复（v2 加 batch state file）
- 平台密码 reset 不失效问题上报（[[tpt-password-history-quirk]]）

---

## 8. 关联文档

- [requirement.md](requirement.md) — 需求文档
- [../README.md](../README.md) — 用户实现的入口（待写）
- 平台行为备忘：[[tpt-password-history-quirk]], [[tpt-ums-endpoint-namespace]]
