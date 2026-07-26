# DataFactory 实时工作区：Phase Q 质量门禁与 A–D 最终收口工作文档

> 适用仓库：`StupidArthur/supcon_tools`  
> 主要工作区：`review3/`  
> 当前主分支基线：`origin/main = 880b4e5`  
> 当前候选审查分支：`review/realtime-closure-a-d = b1be304`  
> 当前状态：候选实现，未合并主分支  
> 本文用途：作为下一位 Agent 的首条工作指令和固定验收合同

---

## 0. 任务目标

不要继续直接开发阶段 E–H，也不要继续按“发现一个问题、修一个问题”的方式反复迭代。

本次任务分为两个部分：

1. 建立 **Phase Q：可重复执行的实时工作区质量门禁**；
2. 使用这些门禁，对 `880b4e5..b1be304` 的 A–D 实现做一次性最终收口，并形成一个可合并到 `main` 的绿色候选。

最终目标不是“多写几个测试”，而是建立以下闭环：

```text
冻结验收合同
+ 一键质量门禁
+ 真实鉴权冒烟
+ 生命周期失败路径测试
+ Wails 生产 API 面检查
+ 大规模订阅性能验证
+ Agent 自我红队审查
```

完成本任务后，A–D 应只再接受一次最终代码审查；通过后立即合并，不再扩大验收范围。

---

## 1. 工作纪律

开始前执行：

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/review/realtime-closure-a-d
```

必须确认：

```text
本地 HEAD = b1be30443ae0c517bff53ec9931a41a65b1c3a40
远端 review/realtime-closure-a-d = b1be30443ae0c517bff53ec9931a41a65b1c3a40
origin/main = 880b4e5d3e2844aff687024843f4b7c3cee6dc3d
```

仓库中 `todo/` 有历史未提交变更：

```text
不要修改
不要暂存
不要提交
不要清理
不要用 git checkout/restore 覆盖
```

其他纪律：

1. 只修改 `review3/` 以及本任务明确新增的测试/脚本/文档。
2. 不 force-push `main`，不 rebase `origin/main`，不重写既有历史。
3. 所有新提交先进入 `review/realtime-closure-a-d`。
4. 只有全部门禁通过后，才允许快进或合并到 `main`。
5. 不允许通过关闭鉴权、删除测试、降低断言、跳过失败场景使门禁变绿。
6. 不允许把 token、密码、绝对用户路径或敏感运行信息写入日志、文档、测试产物、归档 metadata 或 `session.json`。
7. 不允许手工编辑 Wails 生成文件来掩盖 Go 公共 API 设计问题。
8. 每个自动化门禁必须返回可靠退出码；失败时退出非零。
9. 每个新发现的可重复问题都必须尽量转换成自动化检查，不再只写进人工审查意见。
10. Agent 在汇报前必须完成一次独立的自我红队审查。

---

## 2. 系统背景

实时功能由三层组成：

```text
React / TypeScript 前端
        ↓ Wails bindings
Go 配置、会话、进程管理层
        ↓ 子进程、REST 调用
Python DataFactory 实时引擎
        ↓
FastAPI REST / WebSocket / OPC UA
```

主要运行链路：

```text
RealtimeRunPage
→ useRealtimeRunSessionStore
→ RealtimeRuntimeBinding.StartProject / StartSingleYAML
→ Manager 编译实时工程
→ SystemBinding.Start
→ standalone_main.py
→ Engine + FastAPI + OPC UA
→ readiness / status / tags / snapshot
→ 前端 REST + WS
→ RuntimeFrame / 位号表 / 趋势 / 强制 / 报警 / 画面
```

A–D 阶段内容：

```text
A  鉴权启动与 REST/WS token 贯穿
B  进程退出、session、token 和临时目录生命周期
C  报警、归档、session.json 启动事务与回滚
D  WebSocket 按 tag 订阅及前端订阅来源聚合
```

当前候选分支已经有 14 个提交，包含三轮修复。不能只根据提交说明判断完成度，必须以自动化门禁和实际代码为准。

---

## 3. 冻结验收合同

以下是本轮固定验收标准。后续 reviewer 不应再把普通重构建议、风格建议或阶段 E–H 功能临时提升为阻断。

只有以下情况允许新增阻断项：

```text
无法构建
安全边界被破坏
数据可能损坏
子进程或资源可能失管
功能明显不符合本合同
```

### 3.1 功能合同

1. 正常鉴权模式下可以启动实时工程或单 YAML。
2. readiness、Go→Python REST、前端 REST 和 WS 使用同一运行 token。
3. 旧 token 在停止、异常退出或新一轮启动后失效。
4. 正常停止先 flush 归档，再停止 Python，再清 session/token/临时目录。
5. Stop 失败且进程仍运行时，session、token、目录和可重试控制状态保留。
6. 第二次 Stop 必须真正重新执行终止操作，而不是重复返回第一次缓存错误。
7. 应用关闭时，归档关闭先于 Python 终止；最终必须尽力确认子进程退出。
8. 位号表以完整 tag catalog 为行源，不因过滤 snapshot 自我收缩。
9. 位号表、趋势、dashboard、force 的订阅来源以并集合并。
10. WS 重连后自动恢复最终订阅集合。
11. `undefined`、`null`、`[]` 和非空 tag 数组语义明确且有测试。
12. 超过订阅上限时明确报错，不静默丢 tag。

### 3.2 状态合同

#### 启动成功

```text
SystemStatus.running = true
SystemStatus.apiReady = true
RealtimeRunSession.state = running
token 非空
session.json 存在
childPid 为真实子进程 PID
```

#### 启动事务失败且进程已停止

```text
SystemStatus.running = false
RealtimeRunSession = nil
token 为空
本次 session 目录删除
归档已停止或未启动
```

#### 启动事务失败且进程仍运行

```text
RealtimeRunSession.state = stop-failed 或 recovery-required
session 目录保留
token 保留
可以再次 Stop
不得形成无人管理的运行进程
```

#### 主动 Stop 成功

```text
归档先关闭并 flush
Python 退出
RealtimeRunSession = nil
token 为空
session 目录删除
前端 WS 关闭
前端当前实时值清理
```

#### Stop 失败且进程仍运行

```text
session 仍可读取
state = stop-failed
session 目录保留
token 保留
UI 显示“停止失败，需要重试”
再次 Stop 会重新执行终止逻辑
```

#### 异常退出

```text
SystemStatus.running = false
RealtimeRunSession = nil
token 为空
session 目录清理
前端 session 卡片消失
前端 runtime 进入已停止状态
错误信息可见
```

### 3.3 生命周期合同

资源创建顺序：

```text
创建 session 目录
→ 编译
→ 启动 Python
→ readiness
→ 推送报警配置
→ 启动归档（可选）
→ 写 session.json
→ 提交 current session
```

正常清理顺序：

```text
停止归档
→ 等待 flush/close
→ 停止 Python
→ 确认进程退出
→ 清 token
→ 清 session
→ 删除 session 目录
→ 前端 session-end cleanup
```

任何清理失败时，不得在资源仍存在的情况下删除唯一管理状态。

### 3.4 安全合同

1. token 仅存在于运行期内存。
2. token 不进入：
   - `session.json`
   - `metadata.json`
   - 工程文件
   - 日志
   - 测试报告
   - Git 仓库
3. Wails 生产绑定不得暴露：
   - `*ForTest`
   - test hook
   - `commandFactory`
   - `readinessChecker`
   - 进程 listener 注册方法
   - 内部 child PID 修补方法
   - cleanup 排序标记方法
4. `DATAFACTORY_NO_AUTH=1` 只能用于明确的开发测试，不得进入正常启动流程。

### 3.5 性能合同

1. 10,000 和 50,000 tag catalog 下，DOM 行数保持有界。
2. 每个 snapshot 不应对完整 50,000 tag catalog 做无必要的全量对象重建。
3. 位号表订阅 effect 只依赖 catalog/filter/scroll 产生的可见 tag 名称，不依赖每帧值对象。
4. 高频 snapshot 不得导致 100ms debounce 永远被取消。
5. WS payload 仅包含订阅 tag 和必要运行元数据。
6. 慢消费者队列不得无界积累旧帧。
7. 趋势缓冲、事件缓冲和订阅集合必须有上限。

### 3.6 非目标

本轮不实现：

```text
Dashboard 七种组件完整功能
Run History 详情/趋势/CSV 完整闭环
通用趋势上一轮叠加和 LTTB
统一错误码全链路
最终阶段 E–H
多实时实例
热更新
云服务
```

这些进入后续阶段，不能阻止 A–D 收口，除非当前 A–D 修改直接破坏了它们已有行为。

---

## 4. Phase Q：质量门禁建设

新增目录建议：

```text
review3/scripts/
review3/artifacts/
```

`artifacts/` 可按仓库习惯选择提交模板或加入 `.gitignore`。不得提交 token 或机器敏感路径。

### 4.1 `scripts/realtime-gate.ps1`

总门禁脚本，按顺序执行：

```text
1. git diff --check
2. 检查 todo/ 未进入 staged/commit
3. Go race tests
4. Frontend vitest
5. TypeScript/Vite build
6. Python 实时相关测试集合
7. Wails 生产 API 面检查
8. Wails build
9. Wails build 后检查工作区差异
10. 鉴权冒烟
11. 生命周期冒烟
12. 订阅规模测试
```

要求：

- 任一步失败立即记录并最终退出非零；
- 输出每个步骤耗时和退出码；
- 可通过参数跳过耗时步骤，但“最终候选”模式禁止跳过；
- 日志中不得打印 token；
- 总结写入：

```text
artifacts/realtime-gate-summary.txt
```

### 4.2 `scripts/verify-wails-bindings.py`

功能：检查 Wails 生成的生产 API 面。

至少检查：

```text
frontend/wailsjs/go/bindings/*.d.ts
frontend/wailsjs/go/bindings/*.js
frontend/wailsjs/go/models.ts
```

禁止模式：

```text
ForTest
TestHelper
commandFactory
readinessChecker
AddExitListener
SetChildPid
IsPriorityCleanup
terminateErrorOverride
```

注意：不要仅靠字符串粗暴误报文档文本。应检查导出函数、生成模型或明确 API 声明。

输出：

```text
artifacts/wails-api-surface.txt
```

内容至少包含：

```text
绑定名称
导出方法列表
新增/删除 API
禁止 API 命中结果
```

### 4.3 `scripts/verify-realtime-secrets.py`

扫描候选 diff 和 artifacts：

```text
Bearer 实际 token
apiToken 值
session token
常见 32/64 字节随机 hex/base64
用户绝对路径
```

允许出现字段名和占位符，不允许出现真实敏感值。

### 4.4 `scripts/realtime-auth-smoke.ps1`

不设置 `DATAFACTORY_NO_AUTH`，真实验证：

```text
启动最小实时配置
→ readiness 成功
→ GetConnectionInfo 返回 token-present
→ 无 token REST 401
→ 错 token REST 401
→ 正确 token REST 200
→ 无 token WS 4401
→ 正确 token WS 连接并收到 snapshot/heartbeat
→ Stop
→ 旧 token 再请求返回 401
→ 再次启动生成新 token
→ 旧 token 仍 401，新 token 200
```

日志只能输出：

```text
token present: true
token length: N
token rotated: true
```

不得打印 token 内容。

输出：

```text
artifacts/auth-smoke-summary.txt
```

### 4.5 `scripts/realtime-lifecycle-smoke.ps1`

至少验证以下场景：

#### 场景 1：正常停止

```text
archive start
→ archive stop 带 Bearer
→ Python stop
→ token 清空
→ session 清空
→ session 目录删除
```

#### 场景 2：异常退出

```text
外部终止 child process
→ SystemStatus.running=false
→ token 为空
→ session=nil
→ session 目录删除
→ 前端/事件状态可同步
```

#### 场景 3：真实停止失败后重试

第一次：

```text
Interrupt/Kill 路径真实返回失败或 wait timeout
→ session.state=stop-failed
→ token/目录/current 保留
```

第二次：

```text
再次执行真实 Kill/等待
→ 进程退出
→ 全部状态清理
```

不得仅使用在 `stopOnce` 之前直接返回的 override 模拟。

#### 场景 4：应用关闭

```text
Lifecycle.Shutdown
→ archive stop
→ Python 终止
→ 进程确认退出
→ token 清空
→ session 清理
→ listener 最后注销
```

输出：

```text
artifacts/lifecycle-smoke-summary.txt
```

### 4.6 `scripts/realtime-scale-test.ps1`

至少测试：

```text
10,000 tag catalog
50,000 tag catalog
30 个可见 tag
8 个趋势 tag
若干 dashboard/force tag
持续高频 snapshot
滚动和搜索
WS 重连
```

记录：

```text
tag 总数
订阅 tag 数
平均 WS payload
最大 WS payload
前端渲染 DOM 行数
每次 snapshot 处理耗时抽样
订阅发送次数
测试持续时间
错误数量
```

关键断言：

1. 过滤 snapshot 后 catalog 行数不缩小；
2. 搜索未订阅 tag 仍可定位；
3. 滚动后新可见 tag 被订阅；
4. 高频 snapshot 不会阻止 debounce 完成；
5. snapshot 更新不触发对完整 catalog 的全量行对象重建；
6. DOM 行数显著小于 catalog 总数；
7. dashboard、force、trend tag 不因位号表滚动丢失；
8. 超过 5000 返回明确错误。

输出：

```text
artifacts/scale-summary.txt
```

---

## 5. A–D 一次性最终收口清单

完成 Phase Q 后，使用门禁检查 `b1be304`，只处理以下固定问题。

### 5.1 移除生产 Wails 绑定中的内部/测试 API

当前问题：真实 Wails build 已把测试和内部方法暴露到前端。

必须移除或私有化：

```text
SystemBinding.AddExitListener
SystemBinding.SetDataFactoryPathForTest
SystemBinding.SetCommandFactoryForTest
SystemBinding.SetReadyPollIntervalForTest
SystemBinding.SetReadyTimeoutForTest
SystemBinding.SetReadinessCheckerForTest
RealtimeRuntimeBinding.IsPriorityCleanup
RealtimeRuntimeBinding.SetChildPid
```

同时删除或迁移：

```text
internal/bindings/test_helpers.go
```

建议实现方式：

1. 测试 helper 放到 `_test.go`；
2. 跨包测试若必须访问内部逻辑，优先：
   - 改为同包测试；
   - 构造专用内部 adapter；
   - 测试 Lifecycle 顺序时使用普通 fake receiver，而不是给生产绑定加公共方法；
3. Lifecycle 清理顺序通过构造参数或内部类型明确表达，不通过 Wails 可见公共方法表达；
4. child PID 直接在 `launch()` 内部写入，不需要公共 `SetChildPid`。

完成后执行 Wails build，生成文件中不得再出现上述导出。

### 5.2 让进程终止真正可重试

当前 `proc.stopOnce` 会永久缓存第一次失败，阻止第二次真正发送 Interrupt/Kill。

目标设计：

```text
防止并发重复终止
≠
禁止失败后的后续重试
```

可选实现：

```go
stopMu         sync.Mutex
stopInProgress bool
lastStopErr    error
```

每次 Stop：

```text
加锁检查是否已有并发 stop
→ 若进程已 done 返回成功
→ 执行 Interrupt
→ 等待
→ 必要时 Kill
→ 等待
→ 保存结果
→ 释放 stopInProgress
```

如果失败且进程仍存活，下一次调用必须重新执行 Kill/等待。

必须加入真实语义测试，不允许仅在终止逻辑前直接 override 返回。

### 5.3 应用关闭失败路径必须 fail-safe

要求：

1. `RealtimeRuntimeBinding.Cleanup()` 如果 Stop 失败且进程仍运行：
   - 不立即注销 exit listener；
   - 保留 session/token/目录；
   - 继续进入最终强制终止策略。
2. `SystemBinding.Cleanup()`：
   - 终止失败且进程仍存活时不得清 `b.proc`；
   - 不得让 `monitorProcess()` 因 `isCurrent=false` 跳过 token/session 清理；
   - 应记录关闭错误。
3. 最终确认进程退出后，再：
   - 清 token；
   - 清 session；
   - 删除目录；
   - 注销 listener。

Lifecycle 本身不能返回 error，可以：

```text
记录日志
保存 last shutdown error
执行最后的硬终止尝试
```

### 5.4 位号表订阅与值更新解耦

当前问题：`tags` 依赖 `latestFrame/rawSnapshot`，每个 snapshot 都会遍历完整 catalog 并重启 debounce。

必须拆分：

```ts
numericNames       // 仅依赖 tagCatalog + validTags
filteredNames      // 仅依赖 numericNames + filter
visibleNames       // 仅依赖 filteredNames + scrollTop
visibleRows        // visibleNames + 当前 frame 值
```

订阅 effect 只能依赖：

```text
visibleNames
registerSubscription
```

不得依赖：

```text
latestFrame
rawSnapshot
每帧重建的全量 tags 对象
```

渲染阶段只对可见几十行读取当前值。

必须增加测试：

```text
持续推送 20–100Hz snapshot
→ 可见订阅在 100ms 后仍会发送
→ 订阅发送次数不会等于 snapshot 数
→ catalog 处理不随每帧全量重建
```

### 5.5 修正 archiveActive 实际状态

Stop 开始时：

```text
archiveActive=true
→ archive stop 成功
→ system stop 失败
```

此时内部 `archiveActive` 应为 false，不能恢复为 true。

规则：

```text
archive stop 成功 → false
archive stop 失败 → true 或 unknown
未启动 → false
```

第二次 Stop 不应对已成功关闭的 archive 重复请求。

### 5.6 前端显示 stop-failed 并刷新 session

`useRealtimeRunSessionStore.stop()` catch 中：

```text
调用 GetSession
→ 更新 session.state
→ 保留错误
```

UI 必须显示：

```text
停止失败，实时进程仍在运行，需要重试。
```

停止按钮保持可用。

### 5.7 Dashboard 订阅必须校验运行工程身份

当前 dashboard 使用当前编辑工程，而运行实例可能是另一工程。

规则：

```text
session.sourceKind != project → 不注册 project dashboard tags
session.projectId != projectId → 不注册 dashboard tags
session.projectId == projectId → 注册 active page tags
```

不匹配时显示：

```text
当前运行的是工程 A，此画面属于工程 B。
```

不得把工程 B 的 tag 发送给工程 A 的运行实例。

---

## 6. Agent 两阶段工作法

同一 Agent 必须执行两遍。

### 6.1 第一遍：实现者

1. 建立 Phase Q 脚本；
2. 运行脚本得到当前失败基线；
3. 按固定收口清单修改代码；
4. 补充测试；
5. 全部门禁通过。

### 6.2 第二遍：破坏性审查者

实现完成后，不立即汇报。重新从 reviewer 视角检查完整 diff：

```text
失败路径是否真的进入目标代码
测试是否是空验证
mock 是否绕开真实终止逻辑
测试 hook 是否进入生产绑定
Stop 失败后是否还能真实重试
Cleanup 失败后是否丢失进程引用
token 是否可能在退出后残留
archiveActive 是否与实际资源状态一致
高频 frame 是否取消 debounce
dashboard 是否订阅错误工程
Wails build 是否产生意外 API
生成文件是否仍需手工修改
```

第二遍发现的问题必须自行修复，再跑 `realtime-gate.ps1`。

---

## 7. 测试命令

先确认仓库真实脚本名称。最终候选至少执行：

```powershell
cd review3/config-tool

go test -race ./internal/realtime/... ./internal/bindings/... ./internal/app/... -count=1

cd frontend
npm test -- --run
npm run build
cd ..

# Python：必须运行完整实时相关集合，不只 test_engine_api.py
python -m pytest <完整实时相关测试文件列表> -q

wails build

cd ..
powershell -ExecutionPolicy Bypass -File scripts/realtime-gate.ps1 -Mode Final
```

如果全量 `python -m pytest tests/` 因既有性能测试超时：

1. 明确列出被排除文件；
2. 运行所有实时相关测试；
3. 不允许只运行 35 个 `engine_api` 测试冒充完整实时测试。

---

## 8. 提交策略

建议提交序列：

```text
1. test: add realtime quality gates and evidence reports
2. fix: remove internal methods from wails production bindings
3. fix: make process termination retryable and shutdown fail-safe
4. perf: decouple virtual tag subscriptions from snapshot values
5. fix: align archive state and realtime recovery UI
6. fix: scope dashboard subscriptions to the running project
7. test: close realtime A-D lifecycle and scale gaps
```

允许合并相邻小项，但不允许单个巨大、难审查提交。

每个提交必须：

```text
可构建
相关测试通过
不包含 token
不包含 todo/
不包含二进制产物
可独立回退
```

---

## 9. 证据包

最终候选必须在分支中提供或在汇报中附上以下证据：

```text
artifacts/realtime-gate-summary.txt
artifacts/wails-api-surface.txt
artifacts/auth-smoke-summary.txt
artifacts/lifecycle-smoke-summary.txt
artifacts/scale-summary.txt
```

证据内容不得包含 token、用户名、个人目录或机器敏感信息。

### 汇报格式

```text
最终 HEAD:
远端 review 分支:
origin/main:

冻结验收合同：
项目 | 结果 | 证据文件/测试
鉴权启动
旧 token 失效
异常退出清理
Stop 失败真实重试
应用关闭归档顺序
Wails API 面
catalog 驱动位号表
高频 snapshot debounce
dashboard 工程身份
50k tag 规模

提交：
Commit | 标题 | 关键内容

实际执行命令：
- command
  exit code
  result

Wails 导出 API 差异：
- removed
- added
- forbidden hits

已知偏差：
- 无 / 明确列出

工作区：
- git status --short
- todo/ 状态
```

禁止只报告“多少个测试通过”。

---

## 10. 最终合并条件

只有全部满足时，A–D 才可合并到 `main`：

```text
1. realtime-gate.ps1 Final 模式退出 0
2. 正常鉴权真实启动成功
3. 无 token/错误 token/旧 token 均被拒绝
4. WS token 和重连订阅成功
5. Stop 第一次真实失败后，第二次能真实重试并完成清理
6. 应用关闭最终不会失管子进程
7. 归档 stop 在 Python 终止前完成
8. Wails 生成绑定不含测试/内部 API
9. Wails build 后无手工生成文件漂移
10. 位号表不自我过滤
11. 高频 snapshot 不会阻止 debounce
12. 50,000 tag 测试有实际结果
13. dashboard 不向错误运行工程发送 tag
14. stop-failed 在前端可见且可重试
15. Go race、Frontend、Python 实时测试、Wails build 全绿
16. todo/ 未进入提交
17. origin/main 在最终确认前仍保持 880b4e5
```

通过后：

```text
将 review/realtime-closure-a-d 合并/快进到 main
→ 确认 origin/main 与最终绿色 HEAD 一致
→ 删除或保留审查分支按项目规范处理
→ 再开始阶段 E–H
```

---

## 11. Reviewer 固定边界

下一轮审查只检查：

1. 本文冻结合同；
2. Phase Q 脚本是否可靠；
3. 证据包是否真实支持结论；
4. 是否存在构建、安全、数据损坏、进程失管或合同违背问题。

以下内容不再阻止 A–D 合并：

```text
普通代码风格
非关键重构建议
Dashboard 阶段 E 功能完整度
Run History 阶段 F 功能完整度
趋势阶段 G 功能完整度
错误码/E2E 文档阶段 H 的非 A–D 部分
```

若审查发现新的可重复问题，应优先要求增加 gate，而不是继续无限追加人工检查项。

---

## 12. 开始执行时的第一份输出

Agent 在改代码前先输出：

```text
已确认 HEAD / origin/main / review 分支
已阅读文件清单
A–D 当前调用链摘要
Phase Q 将新增的脚本
预计修改文件
预计提交序列
预计测试命令
发现的文档与代码不一致点
```

随后连续工作，不需要每个小步骤等待确认。只有遇到以下情况才停止：

```text
需要修改冻结合同
需要破坏 main 历史
无法避免提交敏感信息
关键测试无法在当前环境运行且没有可靠替代
发现仓库基线与本文描述不一致
```

---

**核心原则：先建立可重复质量系统，再一次性完成 A–D 收口。不要再进行第四轮“人工发现一个问题、Agent 修一个问题”的循环。**
