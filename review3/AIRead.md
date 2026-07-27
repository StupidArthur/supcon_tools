# AIRead.md

> 给后续 AI 协作者的现状摘要。
> 本轮（2026-07-27）从 `df01221` 阶段一路推进后留下的未解决问题。

---

## 背景

`config-tool.exe` 是 Wails 编译的 Go 桌面应用，负责 UI 和拉起常驻服务；
`DataFactoryService.exe` 是 PyInstaller 打包的 Python 后台服务（uvicorn + FastAPI）。
两个 EXE 协同方式：Wails 在启动阶段通过 `service_manager.go` 启动 service，
随机挑选 127.0.0.1 端口、生成 Token、轮询 `/api/health` 直到就绪，再把 token
+ port 注入到前端 runtime store。前端所有 runtime / batch / validate / export
调用都通过 Go 这层代理转发到 service。

详见 todo.md §3–§16。

---

## 当前未解决问题：`config-tool.exe` 在生产 EXE 上拉起 service 失败

### 状态：**已解决（2026-07-27）**

最终根因 + 修复见下方"最终根因"一节。

---

## 现象（已修复）

将 `build/bin/`（含 `config-tool.exe` + `DataFactoryService.exe` + `project/` + `template/`）
整体拷贝到生产目录（例如 `D:\stock\bin`，**无 Go、无 Python、无源码**）后双击
`config-tool.exe`：

- Wails webview2 窗口闪一下（约 0.5s）就关闭
- `ct-stderr.log` 写到 `DataFactory 组态工具启�?` 后停住（**实际是 "启动" 完整**，
  PowerShell 80 列终端截断造成的假象，参见下方"已知假象"）
- 没有 service 进程残留
- 端口 8765 / 任何随机端口都没在 LISTEN

**手动单跑 `DataFactoryService.exe --service --api-port <port>` 完全正常**：
service 进程稳定，端口 LISTENING，`/api/health` 返回
`{"ok": true, "serviceState": "ready", "runtimeState": "stopped"}`。

service EXE 本身是好的，错在 `config-tool.exe` 拉起 service 的链路。

### 最终根因

`config-tool/internal/bindings/service_client.go` 的 `http.Transport` 配置
不正确：

```go
// 错误写法（看似禁用代理，实际仍走 ProxyFromEnvironment）：
Transport: &http.Transport{Proxy: nil}
```

Go 文档坑：`http.Transport.Proxy` 字段是
`func(*http.Request) (*url.URL, error)`。`Proxy: nil` **不等于禁用代理**，
而是让 `Transport` 调用默认的 `ProxyFromEnvironment`，
**仍然会读取** `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 环境变量。
在配置了系统代理的生产机上，127.0.0.1 的请求被路由到外部代理服务器，
1s probe timeout 内全部超时，5 次重试都失败 → `NewDataFactoryServiceManager`
返回 error → `main.go:22` `log.Fatal(err)` → webview2 窗口闪关。

正确写法：

```go
func directProxy(*http.Request) (*url.URL, error) { return nil, nil }
Transport: &http.Transport{Proxy: directProxy}
```

返回 `(nil, nil)` 是 Go 标准库明确约定的"直连"信号。

### 修复验证（D:\stock\bin 2026-07-27 18:11）

| 项 | 修复前 | 修复后 |
|---|---|---|
| Health 通过 | ❌ 5 次重试都失败 | ✅ attempt=1 通过 |
| config-tool 进程寿命 | < 1s 闪退 | 7 分钟+ 稳定 |
| service 进程寿命 | < 1s 被 kill | 7 分钟+ 稳定 |
| LISTEN 端口 | 短暂出现后消失 | 持续 LISTENING |
| 外部 health 探测 | 200 ok（手动测） | 200 ok |

ct-stderr.log 实际内容（修复后）：

```
2026/07/27 18:11:40 [service-manager] attempt=1 serviceExe=D:\stock\bin\DataFactoryService.exe cmd.Dir=D:\stock\bin host=127.0.0.1 port=11366 healthURL=http://127.0.0.1:11366/api/health
2026/07/27 18:11:41 [service-manager] attempt=1 started PID=5652 port=11366 healthURL=http://127.0.0.1:11366/api/health
2026/07/27 18:11:43 [WebView2] Environment created successfully
2026/07/27 18:11:44 DataFactory 组态工具启�?  (UTF-8 截断假象)
```

attempt=1 启动后没再出 attempt=2，也没有 startup failure dump — 说明 health 第一次就过了。

---

## 本轮已尝试的修复

| 阶段 | 修改 | 结果 |
|------|------|------|
| ① NewContainer 默认 devMode | `container.go:32-44` 由 `devMode=true` 改为 `devMode=false` | 生产 EXE 不再去找 `standalone_main.py`，但健康检查仍失败 |
| ② 解决 uv 启动崩溃 | `engine_api.py` 加 `log_config=None`；`standalone_main.py` 加标准流兜底；`DataFactoryService.spec` 补 `uvicorn.logging` / `logging.config` / `logging.handlers` hidden imports | 手动跑 service 成功 |
| ③ 改 stdout 重定向 | `service_manager.go` 把 `cmd.StdoutPipe/StderrPipe` 替换为 `cmd.Stdout = *os.File` 重定向到 `<exe>/service-stdout.log` + `service-stderr.log` | 避免 pipe 4KB 阻塞 |
| ④ 增强启动诊断 | `service_manager.go` 加 `cmd.Dir = exeDir`、attempt/started 日志、`waitForHealth` 1s 单次 probe timeout + lastErr 保留 + 超时带 lastErr、`dumpStartupDiag` 在 kill 前 dump PID/port/lastErr/RecentLogs/exitCode/exited | 定位到根因（ProxyFromEnvironment）|
| ⑤ 修 Proxy 闭包 | `service_client.go` 用 `directProxy` 显式返回 (nil, nil) | **修复** |

每一步都验证过可独立 commit（不互相依赖），但 ①/②/③ 单独都不够，④ 是定位关键，⑤ 是真正的修复。

---

## 已知的相关代码位置

| 文件 | 行 | 内容 |
|------|---|------|
| `config-tool/internal/bindings/service_client.go` | 31-50 | `directProxy` 闭包 + `NewDataFactoryServiceClient` Transport 配置 |
| `config-tool/internal/bindings/service_manager.go` | 78-91 | `NewDataFactoryServiceManager` 初始化（exeDir / stdoutPath / stderrPath）|
| `config-tool/internal/bindings/service_manager.go` | 116-189 | 启动循环：cmd.Dir=exeDir、attempt/started 日志、OpenFile、Start、dumpStartupDiag |
| `config-tool/internal/bindings/service_manager.go` | 311-359 | `waitForHealth` 1s probe timeout + lastErr 保留 + 超时带 lastErr |
| `config-tool/internal/bindings/service_manager.go` | 361-374 | `dumpStartupDiag` kill 前 dump |

### 已知假象

`ct-stderr.log` 显示 `DataFactory 组态工具启�?`，不是 panic 截断。
PowerShell 终端 80 列截断造成，文件实际是完整 "启动"。

---

## 本轮已 push 的相关 commit

- `d797c96` fix(service): make DataFactoryService launchable in windowed mode
- `2c80eaf` fix(app): NewContainer 默认 devMode=false
- `d069c7c` fix(service-manager): stdout/stderr 重定向到文件避免 pipe buffer 满
- `1aeb79d` docs: add AIRead.md 记录本轮未解决问题
- （即将 push）fix(service-manager): 增强启动诊断定位 Proxy 根因
- （即将 push）fix(service-client): 显式禁用代理直连 127.0.0.1
