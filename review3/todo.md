下面内容直接作为一个完整任务交给 Agent。当前基线已经确认：`7118e09` 中虽然增加了 `DataFactoryServiceManager` 和 Python 常驻服务 API，但 `InitService()` 未被启动流程调用；实时运行仍调用旧 `SystemBinding.Start()` 创建独立进程；校验和编译仍使用 `exec.CommandContext()`；批量接口仍返回 501；前端仍传入端口 8000。

# Agent 任务：完成 DataFactory 常驻服务的真实接线与全链路迁移

## 0. 任务目标

基于当前 `main`：

```text
7118e09
chore(frontend): 同步 Wails 生成绑定
```

完成常驻 DataFactory 服务的真正落地。

完成后必须满足：

```text
启动 Config Tool
→ 自动创建 EXE 同级 project/ 和 template/
→ 无窗口启动 EXE 同级 DataFactoryService.exe
→ 整个 Config Tool 会话只启动一个 DataFactoryService 进程
→ 打开工程、校验、编译、批量仿真、格式化导出、实时启动和停止全部复用该进程
→ 启动/停止实时运行只改变 Engine 和 OPC UA，不结束后台服务进程
→ 退出 Config Tool 后后台服务退出
```

不得再出现“新增了一套服务 API，但真实业务继续走旧 CLI 子进程”的双轨状态。

以下任意一项存在时，不得报告任务完成：

* `Container.InitService()` 未实际执行；
* `StartProject()` 仍启动新的 DataFactory/Python 进程；
* 工程校验或编译仍执行 `--inspect-project`、`--compile-project` 子进程；
* `SystemBinding.RunBatch()` 仍执行 `--batch` 子进程；
* `/api/batch/run` 仍返回 501；
* 前端仍硬编码 API 端口 8000；
* 构建后的 `DataFactoryService.exe` 不在 `config-tool.exe` 同级；
* 普通用户操作仍会产生额外 Python/DataFactory 进程。

---

# 1. 仓库和用户文件保护

## 1.1 开始前记录

执行：

```bash
git status --short
git rev-parse HEAD
git log -1 --oneline
```

确认 HEAD 是 `7118e09` 或用户之后明确指定的更新提交。

如果 HEAD 已变化，先阅读变化，不得回退用户的新提交。

## 1.2 禁止操作

禁止：

```bash
git add .
git add -A
git reset --hard
git clean
git stash
git stash --include-untracked
```

禁止删除、覆盖或暂存用户现有内容，特别是：

```text
.mimocode/
review3/todo/
review3/todo.md
review3/requirement.md
review3/design.md
review3/*.patch
artifacts/
review3/artifacts/
所有 workplan 文件
```

只按明确文件路径暂存本任务文件。

## 1.3 开发方式

* 直接在当前 `main` 工作；
* 不创建功能分支；
* 不创建临时 worktree；
* 可以按逻辑拆成多个提交；
* 最终必须全部推送到 `origin/main`；
* 不得用测试通过掩盖功能尚未接线。

---

# 2. 开始编码前的调用链盘点

先完成一次静态盘点，并将结果写入本任务完成报告，不要另外修改用户的需求文件。

搜索：

```bash
git grep -n "exec.Command" -- review3/config-tool
git grep -n "exec.CommandContext" -- review3/config-tool
git grep -n "CombinedOutput" -- review3/config-tool
git grep -n -- "--inspect-project" review3
git grep -n -- "--compile-project" review3
git grep -n -- "--batch" review3/config-tool
git grep -n "apiPort: 8000" -- review3/config-tool/frontend
git grep -n "CurrentAPIToken" -- review3/config-tool
git grep -n "GetConnectionInfo" -- review3/config-tool
```

分类每一处：

1. 常驻服务自身唯一启动；
2. 用户业务操作触发的 DataFactory/Python 子进程；
3. 与 DataFactory 无关的系统命令；
4. 测试替身。

最终目标是：

* 生产代码中，只有 `DataFactoryServiceManager` 可以启动 `DataFactoryService.exe`；
* 普通校验、编译、仿真、导出和实时运行不得再启动 DataFactory/Python；
* Python CLI 兼容入口可以保留，但 Config Tool 不得再调用这些 CLI 模式。

---

# 3. 统一应用启动流程

## 3.1 真正启动常驻服务

当前 `Container.InitService()` 存在但未调用。重构容器初始化顺序，使生产启动流程实际执行：

```text
EnsureAppWorkspaceDirs
→ 创建并启动 DataFactoryServiceManager
→ health 与协议版本校验通过
→ 创建依赖服务客户端的 compiler 和 bindings
→ 启动 Wails UI
```

推荐调整：

```go
func NewContainerWithDevMode(devMode bool) (*Container, error)
```

内部顺序必须变为：

1. 确保工作目录；
2. 创建 `DataFactoryServiceManager`；
3. 等待 `/api/health`；
4. 创建 `ServiceRealtimeCompiler`；
5. 创建 realtime manager；
6. 创建 bindings；
7. 注入统一服务客户端；
8. 创建 lifecycle。

不要继续先创建 `PythonRealtimeCompiler`，然后再单独挂一个没有人使用的 Service。

## 3.2 禁止静默降级

删除或停止生产使用当前 `noopCompiler` 静默降级逻辑。

以下情况必须明确失败：

* `DataFactoryService.exe` 缺失；
* 服务进程启动失败；
* health 超时；
* API Token 不匹配；
* `protocolVersion` 不匹配；
* 服务启动后立即退出。

不得继续打开一个“看起来正常但无法校验和运行”的 UI。

错误必须包含：

* 服务 EXE 的实际路径；
* 服务状态；
* 最近有限行日志；
* 原始错误原因。

不得把 Token 写进错误或日志。

## 3.3 启动生命周期不得重复启动

必须保证：

* `NewContainer()`、`Lifecycle.Startup()` 和前端初始化不会各启动一次服务；
* 同一个应用进程最多拥有一个 `DataFactoryServiceManager`；
* `InitService()` 连续调用是幂等的；
* 并发调用也不能启动两个服务。

### 验收

增加测试：

1. 连续调用初始化两次，只调用一次 command factory；
2. 并发调用初始化，仍只创建一个服务进程；
3. 服务已 ready 时再次初始化直接返回；
4. 第一次失败后允许明确重试；
5. 不允许存在两个不同 PID。

---

# 4. 工作目录初始化必须完整闭环

当前正常创建逻辑保留，但修正错误处理。

## 4.1 目录要求

应用启动时确保：

```text
<exe>/project/
<exe>/template/
```

规则：

* 不存在则创建；
* 已存在则直接使用；
* 不清空已有内容；
* 不生成示例文件；
* 路径被普通文件占用则失败；
* 无权限创建则失败；
* 必须基于 `os.Executable()`；
* 不得回退到当前工作目录或用户配置目录。

## 4.2 启动错误不能只写日志

当前 `Lifecycle.Startup()` 只记录目录错误然后继续。修改为：

* 容器构造阶段完成目录初始化；
* 目录初始化失败时不继续启动服务和 UI；
* 返回明确错误。

## 4.3 文件选择器

`ChooseProjectFile`：

```text
默认目录 = <exe>/project/
```

`ChooseYamlForDsl`：

```text
默认目录 = <exe>/template/
```

不得吞掉目录错误后返回空路径。

`mustDefaultDirForChoose()` 应返回：

```go
(string, error)
```

而不是失败时返回 `""`。

### 验收

除已有测试外增加：

1. 应用容器创建后两个目录已存在；
2. `project` 被文件占用时容器创建失败；
3. `template` 被文件占用时容器创建失败；
4. 文件选择器初始化失败返回错误，不静默打开其他目录；
5. 原有目录中的文件不被删除或覆盖。

---

# 5. DataFactoryServiceManager 完整化

## 5.1 作为唯一进程所有者

`DataFactoryServiceManager` 必须成为唯一持有以下对象的组件：

```go
*exec.Cmd
服务 PID
服务 host
服务 port
服务 Token
服务状态
服务 stdout/stderr
服务退出事件
```

其他 binding 不得持有或启动 DataFactory 进程。

## 5.2 统一认证客户端

当前 `HTTPClient()` 返回普通 `http.Client`，并不会自动添加 Token。

增加统一服务调用层，例如：

```go
type DataFactoryServiceClient interface {
    DoJSON(ctx context.Context, method, path string, request any, response any) error
    OpenSnapshotStream(ctx context.Context, handler func(RuntimeSnapshot)) error
    Host() string
    Port() int
    PID() int
    State() ServiceState
}
```

所有请求必须统一：

* 拼接 `http://127.0.0.1:<动态端口>`；
* 设置 `Authorization: Bearer <token>`；
* 设置 `Content-Type: application/json`；
* 限制响应体大小；
* 检查 HTTP 状态码；
* 解析 FastAPI `detail`；
* 转换成清晰的 Go 错误；
* 不在错误中打印 Token。

禁止各 binding 自行拼 URL、各自管理 Token。

## 5.3 health 校验

`/api/health` 必须校验：

```json
{
  "ok": true,
  "protocolVersion": 1,
  "serviceState": "ready"
}
```

仅搜索响应字符串中 `"ok": true` 不够。

使用正式 JSON 结构解析。

若版本不匹配，应返回：

```text
DataFactoryService 协议版本不匹配：
Config Tool 需要 1，服务返回 2
```

## 5.4 端口竞争处理

当前做法是先选一个空闲端口再关闭监听器，子进程启动前存在竞争窗口。

至少实现：

* 服务启动 bind 失败时识别端口占用；
* 重新选择端口；
* 最多重试 5 次；
* 每次使用新 Token 或继续安全使用同一 Token；
* 失败后回收前一次进程；
* 不留下孤儿进程。

## 5.5 Windows 无窗口实现

将平台代码拆开：

```text
process_windows.go
process_other.go
```

Windows 代码：

```go
func configureBackgroundProcess(cmd *exec.Cmd)
```

要求：

* 如果 `cmd.SysProcAttr == nil`，再创建；
* 设置 `HideWindow = true`；
* 使用位或合并 `CREATE_NO_WINDOW`；
* 不覆盖已有 `CreationFlags`；
* 不覆盖其他 `SysProcAttr` 字段。

非 Windows 为 no-op。

### 验收

Windows 测试必须真实断言：

```text
HideWindow == true
CreationFlags 包含 0x08000000
原有 CreationFlags 保留
原有 SysProcAttr 不被整体替换
```

当前仅“函数能编译”的测试不合格。

## 5.6 进程异常退出

增加后台 `Wait()` 监控：

* 服务意外退出时状态变为 `failed`；
* 保存退出码和最近日志；
* 通知 SystemBinding、RealtimeRuntimeBinding；
* 当前实时 session 变为异常；
* 前端收到明确状态事件；
* 不自动无限重启；
* 用户退出应用时的正常关闭不记录为异常。

---

# 6. 修复服务优雅关闭

## 6.1 请求体匹配

Go 调用：

```text
POST /api/service/shutdown
```

必须发送合法 JSON：

```json
{}
```

或：

```json
{"reason":"config-tool-exit"}
```

不得发送空 body 给要求 Pydantic body 的端点。

## 6.2 响应检查

必须检查：

* HTTP 2xx；
* JSON `ok=true`；
* 非 2xx 时记录 detail；
* 请求失败后再进入超时强杀流程。

## 6.3 Python 关闭顺序

`/api/service/shutdown` 必须：

1. 如果 runtime 为 running/starting/stopping，执行真实 runtime stop；
2. 等 Engine 线程退出；
3. 停止 OPC UA；
4. flush 并关闭归档；
5. 清理运行期状态；
6. 设置 service stopping；
7. 触发服务主循环退出。

不得只把状态改成 `stopping` 后直接退出进程。

### 验收

1. 无 runtime 时 shutdown 正常退出；
2. runtime 运行中时先停止 runtime；
3. 服务在 5 秒内正常退出；
4. 正常关闭路径不调用 Kill；
5. shutdown 返回 422 时测试必须失败；
6. 模拟服务无响应时才执行强制 Kill；
7. Config Tool 退出后进程列表中无 `DataFactoryService.exe`。

---

# 7. 用常驻服务替换 PythonRealtimeCompiler

## 7.1 新 compiler

实现：

```go
type ServiceRealtimeCompiler struct {
    client DataFactoryServiceClient
}
```

继续实现现有：

```go
type RealtimeCompiler interface {
    Validate(...)
    Compile(...)
}
```

`Validate()` 调用：

```text
POST /api/project/inspect
```

或正式增加并调用：

```text
POST /api/project/validate
```

`Compile()` 调用：

```text
POST /api/project/compile
```

## 7.2 路径要求

Go 发给服务的 source file 必须是规范化绝对路径。

不得依赖 Python 服务当前工作目录。

服务端应验证：

* source id；
* source file；
* replicas；
* output path；
* 文件存在；
* 文件可读。

## 7.3 删除真实业务中的 CLI compiler

`resolveRealtimeCompiler()` 不得再返回 `PythonRealtimeCompiler`。

生产调用链中不得再出现：

```text
--inspect-project
--compile-project
exec.CommandContext
```

`PythonRealtimeCompiler` 可以暂时作为独立 CLI 兼容代码保留，但：

* Config Tool 容器不得实例化它；
* Config Tool 自动化测试不得依赖它；
* 后续可单独删除，不要在本任务中无必要扩大删除范围。

## 7.4 错误兼容

保持现有前端可理解的：

```go
ValidationResult
ValidationError
DuplicateInstance
ExpandedInstance
```

服务 HTTP 错误应转换成现有错误类型，不要让前端直接看到整段 FastAPI JSON。

### 验收

1. 创建工程后验证不启动新进程；
2. 打开工程后验证不启动新进程；
3. 添加 YAML 验证不启动新进程；
4. 修改副本数验证不启动新进程；
5. 启动前编译不启动新进程；
6. compiler command factory 调用次数为 0；
7. 服务 PID 在所有操作前后不变；
8. 原有 duplicate/validation 测试继续通过；
9. `git grep` 确认容器不再创建 `PythonRealtimeCompiler`。

---

# 8. 工程上下文真实同步到服务

## 8.1 打开与新建

工程打开或创建成功后调用：

```text
POST /api/project/open
{
  "projectFile": "绝对路径"
}
```

覆盖：

* 文件选择器打开工程；
* 最近工程打开；
* 新建工程；
* 测试入口 `createProjectAt`。

## 8.2 工程修改

以下操作成功并写入工程文件后调用：

```text
POST /api/project/reload
```

覆盖：

* 添加 YAML；
* 移除 YAML；
* 修改 replicas；
* 修改 runtime；
* 以后统一保存工程时的保存操作。

## 8.3 关闭与切换

* 切换工程时，直接 `/api/project/open` 新工程；
* 用户明确关闭工程时调用 `/api/project/close`；
* 切换普通顶部 Tab 不调用 close；
* 实时运行中不允许切换工程，保持已有约束。

## 8.4 同步失败语义

不得静默忽略服务同步错误。

若磁盘修改已完成，但 reload 失败，错误必须明确：

```text
工程文件已保存，但 DataFactory 后台服务同步失败。
请重试打开工程或重启工具。
```

同时保留当前工程路径，不能把 UI 清成空工程。

增加 `serviceSyncError` 或等价状态，后续成功 reload 后清除。

### 验收

使用 mock service 记录请求：

1. 打开工程产生一次 `/api/project/open`；
2. 打开最近工程产生一次 `/api/project/open`；
3. 新建工程产生一次 `/api/project/open`；
4. 添加 YAML 成功后产生 `/api/project/reload`；
5. replicas 修改成功后产生 `/api/project/reload`；
6. remove 成功后产生 `/api/project/reload`；
7. runtime 修改后产生 `/api/project/reload`；
8. 校验失败、事务未应用时不得 reload；
9. 切换 Tab 不 close；
10. 同步失败时 UI 有明确错误。

---

# 9. 实时运行迁移到服务内 Engine

## 9.1 保持上层 API，替换内部实现

尽量保持前端调用：

```text
RealtimeRuntimeBinding.StartProject
RealtimeRuntimeBinding.Stop
RealtimeRuntimeBinding.GetSession
```

但内部不再创建 DataFactory 子进程。

建议将现有 `SystemBinding.Start/Stop/Status` 转为服务代理，避免大面积破坏现有 store：

```text
SystemBinding.Start
→ POST /api/runtime/start

SystemBinding.Stop
→ POST /api/runtime/stop

SystemBinding.Status
→ GET /api/runtime/status + 服务管理器状态
```

`DataFactoryServiceManager` 是唯一真实进程。

## 9.2 StartProject 流程

完整顺序：

1. 检查服务 ready；
2. 检查没有 runtime；
3. 检查没有 batch；
4. 获取工程 revision；
5. 使用 `ServiceRealtimeCompiler` 编译到 session 目录；
6. 创建 session 记录；
7. 调用 `/api/runtime/start`；
8. 等 runtime state 为 running；
9. 推送报警配置；
10. 启动归档；
11. 写 session.json；
12. 设置 current session；
13. 发出运行状态事件。

不得调用：

```go
exec.Command
SystemBinding 的旧 dfLaunch.command
新的 Python/DataFactory 进程
```

## 9.3 API 参数

请求：

```json
{
  "configPath": "绝对路径",
  "runtimeName": "工程名称",
  "cycleTime": 0.5,
  "opcUaHost": "0.0.0.0",
  "opcUaPort": 18951
}
```

服务 API host/port 不从前端传入，统一由 `DataFactoryServiceManager` 决定。

## 9.4 Stop 流程

停止时：

1. 停止归档；
2. 调用 `/api/runtime/stop`；
3. 确认 runtimeState 为 stopped；
4. 更新 session；
5. 清理 session 临时目录；
6. 清空运行状态；
7. 服务进程继续存活。

若 runtime stop 失败：

* 不得假装停止成功；
* session 变为 `stop-failed`；
* 保留 session 信息供重试；
* 服务进程不得被直接 Kill；
* 用户可再次点击停止。

## 9.5 Service PID 语义

后台服务 PID 整个应用会话固定。

实时运行页面不再显示 PID。

内部诊断可以保存服务 PID，但不得把服务 PID误称为“当前工程进程 PID”。

### 验收

1. 启动 Config Tool 后记录服务 PID；
2. 启动实时运行后 PID 不变；
3. 停止实时运行后 PID 不变；
4. 再次启动运行后 PID 不变；
5. runtime stop 后 `/api/health` 仍返回 200；
6. runtime stop 后校验和编译仍可用；
7. 点击实时启动期间没有新增 Python/DataFactory 进程；
8. `StartProject` 相关测试 command factory 调用次数为 0；
9. 停止失败时 session 保留且可重试；
10. 切换 Tab 不停止 runtime。

---

# 10. 修复 Python runtime 生命周期

## 10.1 runtimeName

`/api/runtime/start` 成功时必须更新：

```python
b.instance_name = req.runtimeName
```

所有：

```text
/api/instances/{name}/...
/ws/snapshot
/status
```

使用同一个真实 runtime name。

## 10.2 启动事务

runtime start 任一步失败时必须回滚：

* Engine clock；
* Engine thread；
* OPC UA；
* force manager；
* quality manager；
* shared data；
* snapshot；
* 临时引用；
* runtime state。

不能出现 OPC UA 启动失败但 Engine 线程仍运行。

## 10.3 停止真实性

`/api/runtime/stop`：

* 设置停止事件；
* 停 OPC UA；
* 等 Engine 线程；
* 线程超时仍存活时返回失败；
* 不得将状态标为 stopped；
* 成功后才标记 stopped。

## 10.4 清理运行期状态

停止成功后清理：

```text
b.engine = None
b.shared_data = {}
b.force_manager 重置
b.quality_manager 重置
b.opcua_server = None
b.engine_thread = None
b.engine_stop_event = None
latest snapshot 清空
snapshot buffer 清空
归档引用清空
报警运行状态清空
```

固定输出和质量码是运行期状态，停止运行后不得泄漏到下一次运行。

## 10.5 Engine 未运行接口

以下接口不得因 `b.engine is None` 抛 AttributeError：

```text
/api/status
/api/instances/{name}/meta
/api/instances/{name}/tags
/api/instances/{name}/snapshot
/api/instances/{name}/params
/api/instances/{name}/override
/api/instances/{name}/writes
/api/force
/api/quality
```

未运行时统一返回明确 HTTP 状态和中文 detail，例如：

```text
409 当前工程未运行
```

health 和 runtime status 仍返回 200。

### 验收

1. start → stop → start 连续 10 次；
2. 每次只有一个 Engine 线程；
3. 每次只有一个 OPC UA 服务；
4. stop 后线程已退出；
5. stop 后 Engine 引用为空；
6. stop 后 force/quality 为空；
7. stop 后运行接口返回 409，不返回 500；
8. OPC UA 端口占用时启动失败且无残留线程；
9. Engine 初始化异常时状态为 failed，允许重新 start；
10. runtimeName 与工程名一致。

---

# 11. 实现真正的进程内批量仿真

## 11.1 禁止保留 501 占位

完成 `/api/batch/run`，不得再返回：

```text
501 batch_run 计划在后续阶段实现
```

## 11.2 抽取现有 CLI 逻辑

从 `standalone_main.py --batch` 抽取可复用函数，例如：

```python
def run_batch_in_process(
    config_path: str,
    cycles: int,
    cycle_time: Optional[float],
) -> BatchRunResult:
```

要求保留：

* `GENERATOR` 模式；
* 现有 cycle 语义；
* snapshot 数据；
* `_sim_time`；
* `_need_sample`；
* display columns；
* plot scales；
* 原有错误语义；
* 原有最大值或边界规则，不新增无需求限制。

## 11.3 API 请求响应

请求至少：

```json
{
  "configPath": "绝对路径",
  "cycles": 1000,
  "cycleTime": 0.5
}
```

响应应能直接转换为现有 Go `BatchResult`，例如包含：

```text
columns
rows
displayColumns
plotScales
cycles
```

避免为了内部传输先生成 CSV 再读回来。

## 11.4 并发约束

服务内部维护批量状态和锁：

* runtime running/starting/stopping 时拒绝 batch；
* 已有 batch 时拒绝第二个 batch；
* batch 运行时拒绝 runtime start；
* batch 结束或失败后必须释放状态；
* batch 不修改当前实时 Engine；
* batch 不覆盖当前工程上下文。

## 11.5 Go 接入

`SystemBinding.RunBatch()` 改为调用：

```text
POST /api/batch/run
```

不得再：

```go
dfLaunch.command(...)
CombinedOutput()
--batch
```

### 验收

1. 10、100、1000 cycle 返回正确行数；
2. GENERATOR 模式不按真实时间等待；
3. display columns 和 plot scales 与旧 CLI 一致；
4. runtime 运行中 batch 返回 409；
5. batch 运行中 runtime start 返回 409；
6. 两个并发 batch 只有一个成功；
7. batch 失败后可以再次 batch；
8. batch 前后服务 PID 不变；
9. batch 不创建临时 DataFactory/Python 进程；
10. 原有前端批量测试全部通过；
11. 原有 acceptance isolation 问题如仍存在，必须在本任务内修复，不再标记为“旧问题无关”，因为本任务正好重构批量并发模型。

---

# 12. 格式化导出接入常驻服务

## 12.1 保留纯 Go CSV

单纯将 rows 写普通 CSV 的纯 Go `ExportCSVRows()` 可以保留，因为它不创建子进程。

## 12.2 DataFactory 格式化导出

所有需要 DataFactory 模板、双行表头、XLSX 或格式转换的操作统一调用：

```text
POST /api/export/convert
```

不得再执行：

```text
--convert-export
DataFactory 子进程
Python 子进程
```

## 12.3 输出规则

必须保持当前产品已有行为：

* CSV；
* XLSX；
* 时间列；
* 采样过滤；
* 表头；
* display columns；
* sheet name；
* 输出目录自动创建；
* 错误不留下半成品文件。

建议使用临时输出文件，成功后原子替换目标文件。

### 验收

1. CSV 导出内容与旧实现一致；
2. XLSX 可正常打开；
3. 空 rows 返回明确错误；
4. 非法格式返回 400；
5. 目标目录不存在时创建；
6. 导出失败不留下损坏目标文件；
7. 导出前后服务 PID 不变；
8. 不创建额外 Python/DataFactory 进程；
9. 连续导出 20 次无文件句柄泄漏。

---

# 13. 前端不得再硬编码服务 endpoint

## 13.1 删除 8000

删除：

```typescript
apiHost: '127.0.0.1',
apiPort: 8000,
```

实时启动参数只包含用户工程运行参数：

```text
cycleTime
opcUaHost
opcUaPort
runtimeName
```

后台 API endpoint 由 Go 自己管理。

验收：

```bash
git grep -n "apiPort: 8000" -- review3/config-tool/frontend
```

结果必须为空。

## 13.2 Token 不暴露给 React

当前 `GetConnectionInfo()` 将 Token 返回给前端。完成以下调整：

* React 不再获取长期后台服务 Token；
* Wails 生成模型中不再暴露 `apiToken`；
* 前端不保存 Token；
* 前端不把 Token拼进 REST 或 WebSocket；
* force、quality、override、tags、snapshot 等请求由 Go binding 代理；
* WebSocket snapshot 由 Go 后端连接 Python 服务，再通过 Wails Event 推送给 React。

可以保留仅 Go 内存中的：

```text
host
port
token
```

## 13.3 Go 代理接口

增加或重构 Wails binding，使前端使用：

```text
GetRuntimeTags(...)
GetRuntimeSnapshot(...)
SetRuntimeValue(...)
SetForce(...)
ClearForce(...)
GetForces(...)
SetQuality(...)
ClearQuality(...)
GetQualities(...)
```

这些方法不得再接收：

```text
apiHost
apiPort
apiToken
```

统一通过服务客户端调用。

## 13.4 Snapshot 事件桥

Go 使用认证连接订阅 Python `/ws/snapshot`，再发出 Wails event，例如：

```text
runtime:snapshot
runtime:connection
runtime:error
```

要求：

* runtime 启动后建立；
* runtime 停止后关闭；
* Tab 切换不重复建立；
* 断线后有限重连；
* service 退出后停止重连并报告错误；
* 不创建多个重复订阅；
* 慢前端只保留最新帧，不积压无限队列。

### 验收

1. 浏览器开发工具和前端 store 中不存在 Token；
2. Wails 生成 TS 模型没有 `apiToken`；
3. 前端没有直接 `fetch(http://127.0.0.1:<service-port>)`；
4. 前端没有直接连接 Python WS；
5. snapshot 仍正常刷新；
6. force/quality/override 仍正常；
7. 切换 Tab 不产生重复帧；
8. 停止后没有继续轮询；
9. 服务退出时前端显示运行异常。

---

# 14. SystemBinding 收口

## 14.1 不再代表 DataFactory 子进程

保留文件对话框、纯 Go 文件处理等通用能力。

对于 DataFactory 能力：

```text
Start
Stop
Status
RunBatch
格式化导出
```

全部改成代理常驻服务。

`SystemBinding` 不得再持有“每次实时运行创建的 DataFactory managedProcess”。

## 14.2 状态语义

建议：

```text
SystemStatus.APIReady
= 常驻服务 ready

SystemStatus.Running
= runtime Engine running/starting/stopping

SystemStatus.PID
= 常驻服务 PID，仅内部兼容
```

前端不得展示 PID。

## 14.3 退出监听

原 `addExitListener` 语义改为监听：

* 常驻服务异常退出；
* runtime 异常结束；
* runtime 正常停止。

不要依赖“子进程退出就代表一次实时运行结束”的旧模型。

### 验收

1. `SystemBinding.Start` 不调用 command factory；
2. `SystemBinding.Stop` 不结束服务进程；
3. `Status.Running` 随 runtime 状态变化；
4. `Status.APIReady` 在 runtime stopped 时仍为 true；
5. 服务异常退出时 `APIReady=false`；
6. runtime 停止后服务 PID仍存在。

---

# 15. 发布构建必须完整

## 15.1 修正 PyInstaller spec

确认模块名正确：

* PyYAML 的 import 模块通常是 `yaml`，不要只写无效的 `PyYAML` hidden import；
* 包含 FastAPI、Uvicorn、asyncua、numpy、controller、components、datacenter；
* 包含运行时需要的资源；
* `console=False`；
* 从任意工作目录可启动。

## 15.2 自动构建和复制

增加统一构建脚本，例如：

```text
review3/config-tool/scripts/build_release.ps1
```

流程：

1. 构建 `DataFactoryService.exe`；
2. 对服务 EXE执行 health smoke；
3. 构建 `config-tool.exe`；
4. 将服务复制到：

```text
review3/config-tool/build/bin/DataFactoryService.exe
```

5. 在发布目录创建：

```text
project/
template/
```

6. 输出两个 EXE 的大小和 SHA256。

不得要求用户手工复制。

## 15.3 生产版禁止回退系统 Python

生产模式：

```text
只允许 <exe>/DataFactoryService.exe
```

服务 EXE 缺失时明确失败。

开发模式可以使用源码 Python，但必须通过明确的开发入口或构建模式，不得在生产版静默回退。

### 验收

构建后目录必须至少有：

```text
build/bin/
├── config-tool.exe
├── DataFactoryService.exe
├── project/
└── template/
```

从该目录复制到另一台机器后，不依赖仓库源代码路径。

---

# 16. 必须增加的测试

## 16.1 Go 单元测试

至少覆盖：

1. 工作目录创建；
2. 工作目录错误不吞掉；
3. 服务只启动一次；
4. 服务 health JSON 和协议版本；
5. 动态端口重试；
6. Token 自动注入；
7. Token 不进入日志；
8. Windows flags 合并；
9. shutdown 发送合法 JSON；
10. shutdown 检查 HTTP 状态；
11. shutdown 超时 kill；
12. 服务异常退出；
13. ServiceRealtimeCompiler validate；
14. ServiceRealtimeCompiler compile；
15. 工程 open/reload 同步；
16. StartProject 调 `/api/runtime/start`；
17. Stop 调 `/api/runtime/stop`；
18. RunBatch 调 `/api/batch/run`；
19. 格式导出调 `/api/export/convert`；
20. 普通操作 command factory 调用次数为 0；
21. 服务 PID 跨操作不变；
22. runtime stopped 时 service ready。

## 16.2 Go race

运行：

```bash
go test -race ./internal/bindings ./internal/config ./internal/realtime ./internal/app
```

若 Windows 环境对部分 race 不支持，报告真实情况，不得伪造。

重点覆盖：

* InitService 并发；
* Start/Stop 并发；
* batch/runtime 互斥；
* service exit callback；
* snapshot event bridge；
* shutdown 与 runtime stop 并发。

## 16.3 Python 测试

至少覆盖：

1. service 无 config 启动；
2. health；
3. auth；
4. project open；
5. project reload；
6. inspect；
7. validate；
8. compile；
9. runtime start；
10. runtimeName；
11. runtime stop；
12. stop 后状态清理；
13. stop 超时；
14. start rollback；
15. runtime 未启动接口；
16. batch 正常；
17. batch 并发；
18. batch/runtime 互斥；
19. export CSV；
20. export XLSX；
21. shutdown 无 runtime；
22. shutdown 有 runtime；
23. start-stop-start 10 次；
24. force/quality 不跨 session 泄漏。

## 16.4 前端测试

至少覆盖：

1. 不再传 API host/port；
2. 不再获取 Token；
3. 不再硬编码 8000；
4. 启动运行按钮；
5. 停止运行按钮；
6. Wails snapshot 事件；
7. Tab 切换无重复监听；
8. runtime error 显示；
9. service unavailable 显示；
10. force/quality/override 通过 Wails binding；
11. 原有全部测试继续通过。

## 16.5 静态门禁测试

增加测试或脚本，至少检查：

```text
config-tool 生产代码中：
- 不调用 --inspect-project
- 不调用 --compile-project
- 不调用 --batch
- 不调用 --convert-export
- 不存在 apiPort: 8000
- 不向前端暴露 apiToken
```

允许这些 CLI 参数继续存在于 Python 独立 CLI 兼容代码中。

---

# 17. 手工端到端验收

必须使用最终发布目录，不得只用源码 pytest 代替。

## 17.1 启动目录验收

1. 删除发布目录中的 `project/` 和 `template/`；
2. 启动 `config-tool.exe`；
3. 两个目录自动创建；
4. 重启应用；
5. 目录内容不被清空；
6. 打开 YML 默认进入 `template/`；
7. 打开工程默认进入 `project/`；
8. 新建工程创建到 `project/<工程名>/`。

## 17.2 进程验收

启动应用后记录任务管理器：

```text
config-tool.exe PID = A
DataFactoryService.exe PID = B
```

依次执行：

```text
打开工程
添加 YAML
修改副本数
保存运行参数
切换三个 Tab
运行批量仿真
导出 CSV
导出 XLSX
启动实时运行
查看实时值
固定输出
解除固定
修改质量码
解除质量码
设置设定值
停止实时运行
再次批量仿真
再次启动实时运行
再次停止
```

每一步记录：

* `DataFactoryService.exe` PID 始终为 B；
* 不出现第二个 DataFactoryService；
* 不出现 python.exe；
* 不出现额外 DataFactory.exe；
* 不弹出命令行窗口；
* 停止实时运行后 B 仍存在；
* 退出 Config Tool 后 B 消失。

## 17.3 无 Python 环境验收

在无系统 Python、无 venv、无仓库源码的 Windows 环境：

1. 复制完整发布目录；
2. 启动 Config Tool；
3. 创建目录；
4. 打开 YML；
5. 新建工程；
6. 添加 YAML；
7. 校验；
8. 批量仿真；
9. CSV 导出；
10. XLSX 导出；
11. 实时运行；
12. OPC UA 连接；
13. 停止；
14. 退出。

任意环节依赖系统 Python则验收失败。

## 17.4 异常验收

测试：

* 删除 `DataFactoryService.exe`；
* 服务端口竞争；
* `project` 被普通文件占用；
* `template` 被普通文件占用；
* OPC UA 端口被占用；
* 工程 YAML 格式错误；
* 服务运行中被任务管理器强制结束；
* batch 执行中点击实时启动；
* runtime 执行中点击 batch；
* runtime stop 超时。

所有情况必须给出明确错误，不得崩溃或留下孤儿进程。

---

# 18. 禁止扩展

本任务不要新增：

* Windows 系统服务安装；
* 开机启动；
* 系统托盘；
* 服务脱离 Config Tool 长期运行；
* 远程网络监听；
* 多用户服务；
* 多工程同时运行；
* 服务自动更新；
* 新报警功能；
* 新归档功能；
* 新工程文件格式；
* 新页面；
* 新模板管理功能；
* 与本任务无关的 UI 重设计。

保留现有产品页面，不要借架构改造重做界面。

---

# 19. 提交要求

建议按逻辑拆分提交：

```text
fix(app): start DataFactory service during Config Tool bootstrap
refactor(compiler): use persistent service for validate and compile
refactor(project): synchronize project context with DataFactory service
refactor(runtime): run engine inside persistent DataFactory service
refactor(batch): move batch execution into persistent service
refactor(frontend): proxy runtime data through Wails without exposing token
build(release): package DataFactoryService beside Config Tool
test(service): add persistent-process integration and acceptance coverage
```

只暂存对应文件路径。

最终推送 `origin/main`。

---

# 20. 完成报告格式

完成报告必须包含以下内容，不得只写“测试通过”。

## 20.1 Git 信息

```text
开始 HEAD
最终 HEAD
提交列表
origin/main 推送范围
```

## 20.2 架构接线证明

明确列出：

```text
Config Tool 启动在哪里启动 service
compiler 在哪里调用 service
工程 open/reload 在哪里同步
runtime start/stop 在哪里调用 service
batch 在哪里调用 service
export 在哪里调用 service
snapshot 如何从 service 到 React
```

## 20.3 旧进程路径清理证明

附上命令结果：

```bash
git grep -n "exec.Command" -- review3/config-tool
git grep -n "exec.CommandContext" -- review3/config-tool
git grep -n -- "--inspect-project" review3/config-tool
git grep -n -- "--compile-project" review3/config-tool
git grep -n -- "--batch" review3/config-tool
git grep -n "apiPort: 8000" review3/config-tool/frontend
git grep -n "apiToken" review3/config-tool/frontend/src
```

逐项解释剩余结果为何合法。

## 20.4 测试结果

报告真实结果：

* Go；
* Go race；
* Python；
* Frontend；
* Wails build；
* PyInstaller build；
* service smoke；
* 发布目录 smoke；
* 无 Python 环境 smoke。

未执行的项目必须写“未执行”，不得用“实现层面验证”代替。

## 20.5 二进制

提供：

```text
config-tool.exe 路径、大小、SHA256
DataFactoryService.exe 路径、大小、SHA256
```

确认二者同级。

## 20.6 PID 验收

提供真实记录：

```text
启动后 PID
校验后 PID
batch 后 PID
runtime start 后 PID
runtime stop 后 PID
再次 start 后 PID
应用退出后进程是否消失
```

不得只描述代码设计。

## 20.7 窗口验收

明确说明：

* 是否真实观察到无命令行窗口；
* 使用什么构建产物；
* 是否运行过 batch、compile、runtime；
* 是否仅通过代码推断。

## 20.8 工作区保护

最后附：

```bash
git status --short
```

确认用户原有 todo、patch、artifact、requirement、design 和 `.mimocode` 内容未被触碰。

---

# 最终完成定义

只有同时满足以下条件才算完成：

```text
DataFactoryService 随 Config Tool 自动启动
+
服务 EXE 随发布包自动放到正确位置
+
校验/编译不再启动子进程
+
batch 不再启动子进程
+
实时运行不再启动子进程
+
导出不再启动子进程
+
前端无固定 API 端口
+
前端不持有后台服务 Token
+
实时 start/stop 不改变服务 PID
+
应用退出后无孤儿服务
+
无 Python 环境实测通过
```

不要再次提交只有骨架、占位接口或“下阶段实现”的版本。
