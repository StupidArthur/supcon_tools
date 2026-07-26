# Realtime 高风险生命周期收口任务

## 任务目标

基于当前 realtime-simple-closure 完成后的状态，继续收口实时运行生命周期中的高风险问题。

本阶段不是新增功能开发。

目标：

1. 修复 terminateProcess 并发模型风险；
2. 修复 Shutdown fail-safe；
3. 保证异常退出、停止失败、重复 Stop 等情况下：
   - session 状态不丢失；
   - token 不泄露；
   - archive 不出现半关闭状态；
   - 前端能够恢复操作；
4. 增加真实测试覆盖。

完成后形成一个或多个独立 commit。

禁止：
- 不修改 DSL 编辑；
- 不修改离线仿真；
- 不修改导出流程；
- 不修改工程组态；
- 不引入新的运行时架构；
- 不重写 realtime runtime。

---

# 一、必须先阅读的代码

开始修改前必须阅读：

## Go

### realtime 生命周期

```
review3/config-tool/internal/bindings/realtime_runtime.go
review3/config-tool/internal/bindings/system.go
review3/config-tool/internal/realtime/
```

重点：

- Start()
- Stop()
- Terminate()
- terminateProcess()
- processAlive()
- Cleanup()
- session 保存逻辑
- exit listener

---

## Go 测试

必须阅读：

```
review3/config-tool/internal/bindings/*test.go
review3/config-tool/internal/realtime/*test.go
```

重点找到：

```
TestStart_StopFailurePreservesSessionForRetry
TestTerminate_Retryable_RealKillAfterOverride
TestLifecycle_ShutdownOrderArchiveBeforeProcessKill
```

理解现有测试模拟方式。

---

## 前端

阅读：

```
frontend/src/features/realtime/
```

重点：

```
RealtimeRunPage.tsx
useRuntimeStore.ts
websocket.ts
```

确认：

- session 状态来源；
- Stop 失败后的 UI 行为；
- token 生命周期。

---

# 二、当前已完成内容（不要重复修改）

以下已经完成：

## 订阅

已完成：

- catalog-driven subscription
- visibleNames 与 snapshot 解耦
- 50000 tag 虚拟化
- subscription overflow

不要再次修改：

```
RuntimeTagTable.tsx
DashboardPage.tsx
```

---

## Dashboard

已完成：

- project session 校验
- single yaml 限制
- subscription gate

不要修改。

---

## Gate

已完成：

```
realtime-gate.ps1
realtime-scale-test.ps1
realtime-lifecycle-smoke.ps1
```

除非发现真实 bug，否则不要扩展。

---

# 三、本阶段问题 1：terminateProcess 并发安全

## 背景

目前风险：

terminateProcess 涉及：

- process kill
- wait channel
- timeout
- retry

可能出现：

1. goroutine A 正在等待进程退出；
2. goroutine B 再次调用 terminate；
3. channel close / send 重复；
4. 状态提前清理。


---

# 四、要求检查点

## 1. terminate 是否幂等

确认：

连续调用：

```
Terminate()
Terminate()
```

不会：

- panic；
- deadlock；
- 清除错误状态。

如果不存在：

增加测试。

---

## 2. channel 生命周期

检查：

- 谁创建 channel；
- 谁关闭 channel；
- 是否可能重复 close。

规则：

channel owner 必须唯一。

禁止：

多个路径 close 同一个 channel。

---

## 3. timeout 后 retry

必须验证：

流程：

```
Start
↓
Terminate
↓
timeout
↓
state preserved
↓
Retry terminate
↓
success
```

要求：

第一次失败：

保留：

```
current session
token
curDir
session.json
child pid
```

第二次成功：

才清理。

---

# 五、本阶段问题 2：Shutdown fail-safe

## 背景

应用退出时：

```
Wails shutdown
|
+-- archive stop
|
+-- system stop
|
+-- session cleanup
```

这里风险最高。

---

# 六、要求实现

## 1. Shutdown 顺序必须明确

正确：

```
archive flush
↓
system stop
↓
session cleanup
```

禁止：

```
system stop
↓
archive stop
```

因为进程停止后可能无法保存最后数据。

---

## 2. 任一步失败不能导致状态丢失

例如：

archive stop失败：

错误：

```
archive error
delete session
```

正确：

```
archive error
keep session
mark dirty
```

---

## 3. Cleanup 必须幂等

重复：

```
Cleanup()
Cleanup()
```

不能：

- panic；
- 删除不存在目录报错；
- 修改错误状态。

---

# 七、必须新增测试

## Go

新增：

## 1. terminate 并发测试

要求：

多个 goroutine 同时：

```
Terminate()
```

验证：

- 无 panic；
- 无 race；
- 最终状态一致。

运行：

```
go test -race
```

---

## 2. shutdown archive failure

模拟：

archive stop 返回 error。

验证：

保持：

```
current != nil
session exists
token exists
```

---

## 3. cleanup 幂等

调用：

```
Cleanup()
Cleanup()
Cleanup()
```

要求：

成功。

---

## 4. terminate retry

完整覆盖：

```
first terminate fail
second terminate success
```

---

# 八、测试要求

必须执行：

## Go

```
go test -race ./internal/realtime/... ./internal/bindings/... ./internal/app/... -count=1
```

必须通过。

---

## Frontend

保持：

```
npm test -- --run
npm run build
```

---

## Wails

如果环境允许：

```
wails build
```

确认：

wailsjs 自动生成没有异常。

---

# 九、提交要求

不要一次提交巨大改动。

推荐：

## Commit 1

```
fix: make realtime termination idempotent and retryable
```

只包含：

- terminateProcess
- process lifecycle
- Go tests

---

## Commit 2

```
fix: harden realtime shutdown cleanup
```

只包含：

- shutdown
- archive failure
- cleanup

---

## Commit 3

```
test: add realtime lifecycle regression coverage
```

只包含：

- 新测试
- gate

---

# 十、最终汇报格式

必须输出：

```
Commit:
SHA:

Changed files:

Problem 1:
terminateProcess:

* before:
* after:
* tests:

Problem 2:
shutdown:

* before:
* after:
* tests:

Verification:

Go:
Frontend:
Python:
Wails:

Known limitations:
```

---

# 十一、重要原则

不要因为测试失败而修改测试绕过问题。

不要：

- 删除 race test；
- 降低 timeout；
- mock 掉核心逻辑；
- 修改测试期待值。

目标：

让 realtime 生命周期在异常情况下仍然可靠。
