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

### 现象

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

所以 service EXE 本身是好的，错在 `config-tool.exe` 拉起 service 的链路。

### 本轮已尝试的修复（commit 0e9.../3a4...）

| 阶段 | 修改 | 结果 |
|------|------|------|
| ① NewContainer 默认 devMode | `container.go:32-44` 由 `devMode=true` 改为 `devMode=false` | 生产 EXE 不再去找 `standalone_main.py`，但健康检查仍失败 |
| ② 解决 uv 启动崩溃 | `engine_api.py` 加 `log_config=None`；`standalone_main.py` 加标准流兜底；`DataFactoryService.spec` 补 `uvicorn.logging` / `logging.config` / `logging.handlers` hidden imports | 手动跑 service 成功，但 service_manager 拉起仍失败 |
| ③ 改 stdout 重定向 | `service_manager.go` 把 `cmd.StdoutPipe/StderrPipe` 替换为 `cmd.Stdout = *os.File` / `cmd.Stderr = *os.File`，重定向到 `<exe>/service-stdout.log` + `<exe>/service-stderr.log`；删 `pumpOutput` / `lineBuffer` / `lineScanner` 死代码；`RecentLogs` 改为读文件尾部 | 文件实际没生成（下面"分析"） |

### 实际观察（最新一次本地验证 D:\stock\bin）

启动 config-tool 后：

- 2 个 `DataFactoryService` 进程短暂存在（说明走到了 `serviceMaxPortRetries` 重试）
- `service-stdout.log` / `service-stderr.log` 文件**被创建但始终为 0 字节**
- 端口 LISTENING 出现在第一个 service 进程上（PID 1），但 `/api/health` 探测失败
- 第二个 service 进程在 5s 内退出（被前一次 health 失败 kill 后重试）
- 5 次重试用尽，`NewDataFactoryServiceManager` 返回 error，
  `NewContainerWithMode` 报 "DataFactoryService 启动失败: ..."，
  `main.go:22` `log.Fatal(err)` → 进程退出 → webview2 窗口闪关

### 分析与猜测（未验证）

1. **service 进程**实际是被拉起、listen 端口成功，但 `/api/health` 探测超时
   - `waitForHealth` 用 200ms 间隔轮询 15s，应该足够
   - 可能是 uvicorn 启动卡在某个 import / 注册阶段，绑了端口但还没开始 accept
2. **service-stdout.log / service-stderr.log 0 字节**
   - 说明 service 进程实际没向这两个文件写过一行
   - 但 service 单独手动启动时**会**写到 manual-stdout.log
   - 可能是 exec 在 `cmd.Start()` 之后没正确接管文件句柄，或者 service 在能写日志前就因别的原因卡住
3. **5 次重试期间产生 2 个 service 进程**（不是 5 个）
   - 第一个成功 listen 但 health 超时被 kill → 第二个拉起 → 也失败
   - 但配置显示 `serviceMaxPortRetries = 5`，第 3-5 次拉起为什么没产生进程？可能被并发锁跳过

### 已知的相关代码位置

| 文件 | 行 | 内容 |
|------|---|------|
| `config-tool/main.go` | 22 | `log.Fatal(err)` 启动失败时直接退出 |
| `config-tool/internal/app/container.go` | 32-44 | `NewContainer` 选择 devMode + wailsGenerateMode |
| `config-tool/internal/app/container.go` | 73-78 | `NewDataFactoryServiceManager` 失败时 service 已被内部回收，error 上抛 |
| `config-tool/internal/bindings/service_manager.go` | 130-170 | 进程启动循环：pickFreePort → OpenFile → exec → monitorExit → waitForHealth |
| `config-tool/internal/bindings/service_manager.go` | 266-285 | `waitForHealth`：15s 内 200ms 间隔轮询 |
| `review3/datacenter/engine_api.py` | 1871-1900 | `run_api_server`：uvicorn.Config + log_config=None |
| `review3/standalone_main.py` | 23-65 | `_ensure_standard_streams`：noconsole 下 sys.stdout/stderr 兜底 |
| `review3/DataFactoryService.spec` | 30-49 | hidden imports（含 uvicorn.logging 等） |

### 已知的相关测试 / 工具

- `config-tool/scripts/build_release.ps1`：完整 release 打包脚本（含 health smoke）
- `python -m pytest tests/test_engine_api.py`：58 passed
- `go test ./internal/...`：bindings / config / realtime 全过；`internal/app` 无测试

### 已知假象

`ct-stderr.log` 显示 `DataFactory 组态工具启�?`，不是 panic 截断。
PowerShell 终端 80 列截断造成，文件实际是完整 "启动"。

---

## 建议的下一步诊断

按可能性从高到低：

1. **在 service 启动循环里加更细粒度日志** — 把 `cmd.Start()` 之后立刻 `cmd.ProcessState` /
   `m.cmd.Process.Pid` 写到 ct-stderr，验证 service 真的起来了。
2. **在 waitForHealth 失败时把 `RecentLogs()` 写到 ct-stderr** — 现在错误只在
   `NewDataFactoryServiceManager` 返回的 error 信息里带，但 `log.Fatal` 只打 err，
   RecentLogs 内容丢失。改 `main.go` 不 Fatal 而是显示对话框 / 写入 ct-stderr。
3. **不用 cmd 拉起 service，改用 detached 进程**（CREATE_BREAKAWAY_FROM_JOB +
   CREATE_NEW_PROCESS_GROUP）— 排除 Go 父进程对 service 进程句柄的隐式影响。
4. **临时把 service 启动后写一个 sentinel 文件**（`service-stdout.log` 第一行
   "service started"），从 config-tool 侧 grep 这个文件来确认 service 真的
   跑到了 `run_api_server`。
5. **检查 webview2 与 service 的端口冲突** — `pickFreePort` 拿到端口后立刻
   `l.Close()`，有 race 窗口。

---

## 本轮已 push 的相关 commit

- `d797c96` fix(service): make DataFactoryService launchable in windowed mode
- （即将 push）fix(app): NewContainer 默认 devMode=false
- （即将 push）fix(service-manager): stdout/stderr 重定向到文件避免 pipe buffer 满
