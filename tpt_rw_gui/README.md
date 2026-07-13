# tpt_rw_gui

TPT ↔ 下游数据源值读写验证 GUI 工具。

替代 TPT 后台 UI 缺失的"写值"能力,在桌面上验证整条数据通路:
**`登录 -> select 数据源 -> select + 关键字筛位号 -> 读实时 / 写值 / 读历史`**。

## 目录

```
tpt_rw_gui/
├── main.go                       Wails 入口(只挂 Container)
├── wails.json
├── go.mod                        module tpt_rw_gui,replace -> ../tpt_api/go
├── cmd/probe/                    实验性 CLI 探针(直接调 tpt_api,不经 GUI service)
├── internal/
│   ├── app/                      组合根 + Lifecycle(ctx 注入)
│   ├── bindings/                 Wails 边界(SessionBinding / RWBinding)
│   ├── rw/                       值读写业务(service/model/ports/errors/adapter)
│   ├── session/                  登录态业务
│   └── platform/                 系统能力留位(占位,未实现)
├── frontend/
│   ├── package.json              React 18 + Vite + Tailwind + Radix
│   ├── src/
│   │   ├── App.tsx               登录区 + 顶层 session 状态
│   │   ├── components/           TagPickerDialog / VerifyPanel / Toast + ui 基元
│   │   ├── lib/api/              wailsjs 收口(静态 import)+ TS 类型
│   │   └── components/ui/        Button/Card/Input primitives
│   └── wailsjs/                  Wails 自动生成的 JS/TS 绑定(已追踪,免重新生成)
└── tests/
    └── integration/              跨包真实链路(httptest -> tptapi.Service -> RWBinding)
```

## 依赖

- Wails v2(Go 库 v2.13.0)
- Go 1.25+
- React 18 + TypeScript 5 + Tailwind 3 + Radix Slot
- 平台:`github.com/yzc/tpt_api`(本地 `../tpt_api/go`,通过 `replace`)

## 开发

```bash
# 后端单测
go test ./internal/...
go test ./tests/integration/...

# 跑 GUI(wails dev):首次会跑 npm install + vite dev + wails build
wails dev
```

## 关键技术决策

1. **客户端固定 `tptapi.TptClient`**(`tpt_api/go/*_full.go`)。
   - 已登录 `*TptClient` 自带 `sync.Mutex` + 5min JWT 续期(`tptapi.Service.Client()`)。
   - 读写链(`QueryTagsWithQuality` / `GetRTValue` / `WriteTagValues` / `GetHistoryValue` ...)只在 TptClient 上。

2. **后端目录**:按 dev-skill go-architecture 轻量结构。
   - 业务包(`rw`、`session`)不 import Wails。
   - Binding 极薄:DTO 转换 + 错误映射 + 调 Service。
   - 具体依赖在 `internal/app/container.go` 单一组合根构造。
   - `*tptapi.Service` 在 session 与 rw 间共享,登录态一份。

3. **前端栈**:React 18 + Vite + Tailwind + Shadcn 风格自造组件(Radix Slot 用于 Button asChild)。
   - 组件不直接 import `wailsjs/...`,统一走 `frontend/src/lib/api`。
   - `lib/api` 静态 import wailsjs 生成模块;`wailsjs/` 已纳入版本控制,无需先跑 `wails generate`。

4. **错误模型**:
   - 业务包暴露 `*PublicError{Code, Message, Kind}`。
   - Kind ∈ {auth, api, http, parse, input, data}。
   - Wails Binding 返回 `*PublicErrorDTO`(同名 + `Error() string` 给 error 接口)。
   - **注意**:auth Kind 触发前端回 LoginPanel 的机制**计划中,尚未实现**(前端当前不解析 Kind)。

5. **测试**:业务包用 `tptapi.Service.Client()` 接口替身(`rw.NewTptClientAdapter`)注入 fake client;
   集成测试用 `httptest.NewServer` 模拟平台后端,验证 00000 / A0230 链路分类正确。
   - **已知问题**:集成测试的历史值 fake 响应形态与 `tpt_api` 真实契约不一致,待修复。

## 已知限制

- `frontend/wailsjs/` 已纳入版本控制(静态 import);缺文件时前端类型检查会失败,而非运行时 reject。
- 写值回读默认 1000ms(平台实测 ~1s 反映);0 即不回读。
- **写值结果真实性(已知问题)**:`tpt_api/go` 的 `WriteTagValues` 丢弃平台返回的 `failMsg`;前端当前不消费 `WriteResult`,无条件提示成功。待修复。
- **历史值解析(已知问题)**:`parseHistoryMap` / `parseHistoryRecords` 与 `tpt_api` 真实契约(字段名 `tagValue` vs `value`、结构 `records` vs `{tagName:{list,total}}`)不一致。待修复。
- 不做批量写;若日后需要,可扩 `WriteRequestDTO.Values` 多键 + `RWBinding.WriteValues` 改循环。

## cmd/probe(实验性)

`cmd/probe/main.go` 是独立 CLI 探针,直接调用 `tpt_api`(不经 GUI service/binding),用于诊断 TPT 连接和读写链路。

- 支持 `login`/`list`/`rt`/`write`/`history`/`all`/`auto` 子命令。
- 默认读取父目录 `env.json`。
- **警告**:`auto`/`all` 模式会创建 `probe_diag_<timestamp>` 位号并写值,**当前无清理逻辑**,可能污染测试环境。不建议在不了解副作用时运行。

## 已知问题汇总

| 项 | 说明 |
|---|---|
| Wails CLI 版本漂移 | 全局 CLI v2.12.0 vs Go 库 v2.13.0;当前不阻断构建,应统一 |
| 未使用依赖 | `class-variance-authority`、`lucide-react` 在 package.json 中但源码未导入 |
| platform 占位 | `internal/platform/platform.go` 仅 `ErrNotImplemented`,未接入 Container |
| RWBinding.sess 未用 | `internal/bindings/rw.go` 持有 `sess *session.Service` 但未调用 |
| Logout 不清 client | `internal/session/service.go` Logout 只清本地 subject,不清底层 TptClient |
| 登出后轮询不停 | `VerifyPanel.tsx` 的轮询 effect 不依赖 `disabled`,登出后继续 |
| 历史解析契约错 | 见"已知限制" |
| 写失败报成功 | 见"已知限制" |
| 空关键字跨 DS | 空关键字走 `ListGroupTagsRaw`(无 DS 参数),可能选到其他数据源位号 |

## 验证步骤

```bash
go vet ./...
go test -count=1 ./internal/...
go test -count=1 ./tests/integration/...
# 仅前端类型检查(无需真后端):
cd frontend && npx tsc --noEmit
# 完整 GUI 构建:
wails build
```
