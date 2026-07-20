# 单阀门二阶水箱模板：分阶段实施手册

> 本手册是施工卡，不替代产品设计和仓库契约。
>
> Agent 必须先阅读：
>
> 1. `todo/second_order_tank_agent_start_here.md`
> 2. `todo/second_order_tank_visual_dsl_template_design.md`
> 3. `todo/second_order_tank_repository_contracts.md`
>
> 一次只执行一个阶段。每个阶段的退出门禁全部通过后才允许进入下一阶段。

---

## 总体文件边界

### 可以扩展

```text
config-tool/frontend/src/App.tsx
config-tool/frontend/src/style.css
config-tool/frontend/src/lib/
config-tool/frontend/src/features/templates/
config-tool/frontend/src/features/runtime/
config-tool/frontend/package.json
config-tool/frontend/package-lock.json
config-tool/internal/bindings/
config-tool/internal/config/
config-tool/internal/app/
config-tool/main.go
datacenter/engine_api.py
controller/engine.py
standalone_main.py                 仅在真实启动/API 契约需要最小修正时
tests/
```

### 只读真源，原则上禁止修改

```text
components/programs/pid.py
components/programs/valve.py
components/programs/cylindrical_tank.py
components/programs/base.py
datacenter/opcua_server.py
config/单阀门二阶水箱.yaml          内置模板不得被测试或开发过程覆盖
```

如确需修改只读真源，触发停止条件，先汇报。

### 必须保留

```text
config-tool/frontend/src/components/Canvas.tsx
config-tool/frontend/src/components/Palette.tsx
config-tool/frontend/src/components/PropertyPanel.tsx
config-tool/frontend/src/components/SimulationPanel.tsx
config-tool/frontend/src/store/useCanvasStore.ts
```

允许做兼容性接线或修复，但不得删除通用 React Flow 和已有批量视图。

---

## 阶段 0：基线与可构建性

### 目标

建立可重复的开发基线，让现有 `config-tool` 在没有模板功能时也能安装、测试和构建；修复阻止后续工作的缺失 glue code，但不实现模板业务。

### 前置阅读

```text
config-tool/frontend/package.json
config-tool/frontend/src/App.tsx
config-tool/frontend/src/store/useCanvasStore.ts
config-tool/frontend/src/components/Toolbar.tsx
config-tool/frontend/src/components/SystemPanel.tsx
config-tool/frontend/src/components/SimulationPanel.tsx
config-tool/frontend/wailsjs/go/bindings/*.d.ts
config-tool/internal/bindings/*.go
config-tool/main.go
config-tool/wails.json
```

### 主要修改范围

```text
config-tool/frontend/src/lib/api.ts                 新增缺失 wrapper
config-tool/frontend/package.json
config-tool/frontend/package-lock.json
config-tool/frontend/vite.config.ts 或 vitest.config.ts
config-tool/frontend/src/test/                      测试 setup，可选
必要的最小编译修复文件
```

### 必做动作

1. 运行起始指南第 4 节基线命令并记录结果。
2. 创建薄的 `src/lib/api.ts`，只包装 Wails 生成函数，不在 wrapper 中维护业务状态：
   - `componentApi.list()` → `ComponentBinding.List()`；
   - `configApi.importYAML/exportYAML/validate/...` → `ConfigBinding`；
   - `systemApi.getDataFactoryPath/browseExe/listConfigs/start/stop/status/openYAMLFile/saveYAMLFile/runBatch/exportBatch` → `SystemBinding`。
3. 用 `npm.cmd install --save-dev vitest jsdom @testing-library/react @testing-library/user-event` 补充测试依赖并同步 `package-lock.json`；脚本至少有 `test` 和 `test:run`。如果依赖已经在锁文件中则不重复安装。
4. 用 `npm.cmd ci` 从更新后的锁文件做一次干净安装验证；若环境不允许联网且没有缓存，停止并报告，不能伪造 build 结果。
5. 处理当前源码中阻止 TypeScript 构建的错误。只做编译和明显 glue 修复，不重构模板功能。
6. 执行 `wails build`，让 Go binding 重新生成；生成文件只由 Wails 更新。
7. 记录仍存在但不阻止阶段 1 的历史问题，例如未触及页面中的乱码文本。

### 测试

```powershell
Set-Location config-tool\frontend
npm.cmd run test:run
npm.cmd run build
Set-Location ..
$env:GOCACHE = Join-Path ([System.IO.Path]::GetTempPath()) 'review3-go-cache'
go test ./internal/...
wails build
go test ./...
Set-Location ..
python -m pytest tests\test_tank_pid_configs.py tests\test_pid_industrial.py tests\test_structured_dsl.py -q
```

### 退出门禁

- [ ] `src/lib/api.ts` 存在且没有业务状态；
- [ ] 前端 `test:run` 和 `build` 通过；
- [ ] `config-tool/frontend/dist` 可生成；
- [ ] Go 内部测试和完整测试通过；
- [ ] Wails build 通过；
- [ ] 目标 Python 75 项基线测试仍通过；
- [ ] 尚未删除或替换任何旧视图。

---

## 阶段 1：无损 DSL、模板定义和三份配置状态

### 目标

能够无损加载目标 YAML，识别固定模板，编辑白名单字段，校验、另存为、重新加载；建立 `saved/draft/running` 分离状态，但暂不启动 Engine。

### 前置阅读

```text
config/单阀门二阶水箱.yaml
controller/parser.py
config-tool/internal/config/model.go
config-tool/internal/config/service.go
config-tool/internal/config/service_test.go
config-tool/internal/bindings/config.go
config-tool/frontend/src/store/useCanvasStore.ts
```

### 建议新增文件

```text
config-tool/internal/config/template_model.go
config-tool/internal/config/template_service.go
config-tool/internal/config/template_service_test.go
config-tool/internal/bindings/template_config.go

config-tool/frontend/src/features/templates/types.ts
config-tool/frontend/src/features/templates/TemplateWorkspace.tsx
config-tool/frontend/src/features/templates/secondOrderTank/definition.ts
config-tool/frontend/src/features/templates/secondOrderTank/bindings.ts
config-tool/frontend/src/features/templates/secondOrderTank/conversions.ts
config-tool/frontend/src/features/templates/secondOrderTank/validation.ts
config-tool/frontend/src/features/templates/secondOrderTank/SecondOrderTankPage.tsx
config-tool/frontend/src/features/templates/useTemplateStore.ts
```

文件名允许按项目习惯微调，但职责必须分开。

### 必做动作

1. 实现仓库契约第 4 节的无损模板服务，使用 `yaml.v3.Node` 只修改白名单路径。
2. 模板加载必须检查五个固定 program、types、inputs 和 `execute_first`。
3. `display_args`、inputs、program 顺序、注释和未知键在加载/保存后保持。
4. 保存请求必须使用 `expectedHash` 检测外部磁盘修改。
5. 内置模板第一次保存默认“另存为”，不允许静默覆盖。
6. 建立独立模板 store，至少包含：

   ```text
   templateId
   sourcePath
   savedConfig
   draftConfig
   savedContentHash
   runningConfigIdentity
   selectedObjectId
   dirtyPaths
   validationErrors
   validationWarnings
   runtimeState
   ```

7. `latestSnapshot` 即使暂为空也必须与 draft 分字段定义，禁止未来复用同一对象。
8. 实现单位换算、稳态预检查和全部纯函数测试。
9. `App.tsx` 默认进入模板工作区；保留按钮进入现有系统管理、仿真和高级 DSL 组态。
10. 当前阶段页面可以是结构化占位布局，但不得用假运行数据。

### 必须增加的测试

Go：

- 导入当前目标 YAML；
- 修改 Tank 2 半径后另存为临时目录；
- 再次加载仍为新值；
- `display_args`、inputs、`execute_first`、Variable value 全部保留；
- Unicode 文件名；
- 内置模板无确认不覆盖；
- hash 冲突不覆盖；
- 非目标拓扑返回结构化错误；
- 无效值不写盘；
- 写盘失败不破坏原文件。

前端：

- m³/s ↔ L/min；
- outlet_area ↔ diameter_mm；
- 水箱容量；
- 稳态目标流量、阀位和 Tank 1 液位；
- draft/saved/running 一致性；
- dirtyPaths 增删；
- SV 超过 Tank 2 高度；
- 不可达流量和预计溢流。

### 测试

```powershell
Set-Location config-tool\frontend
npm.cmd run test:run
npm.cmd run build
Set-Location ..
go test ./internal/config ./internal/bindings
wails build
Set-Location ..
python -m pytest tests\test_structured_dsl.py tests\test_tank_pid_configs.py -q
```

### 退出门禁

- [ ] 目标 YAML 可无损往返；
- [ ] 保存文件可被 Python DSLParser 解析；
- [ ] saved/draft/running 三份状态不混用；
- [ ] 内置模板保护和 hash 冲突有效；
- [ ] 合法性和稳态预检查有纯函数测试；
- [ ] 通用 React Flow 导入/导出回归测试仍通过；
- [ ] 默认模板页面可打开，但没有伪运行值。

---

## 阶段 2：固定 SVG P&ID 和对象检查器

### 目标

在停止/组态状态下完成真实工业流程图外观、对象选择和右侧组态检查器。所有显示值来自 draft 初值。

### 前置阅读

```text
todo/second_order_tank_visual_dsl_template_design.md 的第 7～10 节
config-tool/frontend/src/features/templates/secondOrderTank/definition.ts
config-tool/frontend/src/features/templates/useTemplateStore.ts
config-tool/frontend/src/components/PropertyPanel.tsx       只参考交互，不复制结构
```

### 建议新增文件

```text
config-tool/frontend/src/features/templates/ObjectInspector.tsx
config-tool/frontend/src/features/templates/RuntimeToolbar.tsx
config-tool/frontend/src/features/templates/secondOrderTank/SecondOrderTankDiagram.tsx
config-tool/frontend/src/features/templates/secondOrderTank/SecondOrderTankInspector.tsx
config-tool/frontend/src/features/templates/secondOrderTank/*.test.tsx
```

### 必做动作

1. 用单个响应式 SVG 绘制水源、入口管线、阀门、Tank 1、Tank 2、排水、LT、LIC/PID、PV/MV 信号线。
2. 不使用 React Flow 绘制普通模板主画面。
3. 每个对象具有稳定 `data-testid` 和选择 ID；支持点击、键盘聚焦和选中高亮。
4. 停止状态：Tank 1/2 使用 `initial_level`，阀门使用 `initial_opening`，Tank 2 显示 SV 标线。
5. 明确显示“当前为组态预览，不是实时值”。禁止 CSS 定时器驱动假流动。
6. 右侧标题同时显示中文名、实例名和组件类型。
7. 检查器分“组态 / 运行 / 趋势”页签；当前阶段运行页只显示“未运行”，趋势页只配置推荐位号。
8. 字段展示原始 YAML 参数名、单位、范围、生效方式、帮助文本；高级字段折叠。
9. 编辑后立即更新 draft、dirty 和校验，但不改 saved。
10. 最低 1024×700 可用；右侧检查器固定合理宽度，中心 SVG 自适应。

### 组件测试

- 默认显示 72 L/min、84.8 L、0.15/0.10 m、0.8 m SV；
- 点击水源、阀门、Tank 1、Tank 2、LT、PID 切换检查器；
- 停止态液位来自 draft `initial_level`；
- Tank 2 SV 标线比例正确并限制在容器内；
- 修改字段产生 dirty，不改变 saved；
- 无选中对象时显示模板说明，不是空白；
- 1024×700 容器下关键操作可见。

### 退出门禁

- [ ] 流程图看起来是简化 P&ID，不是节点方框图；
- [ ] 所有要求对象都能选择；
- [ ] 组态值和单位正确；
- [ ] 停止状态没有假运行动画；
- [ ] 对象检查器字段、校验和 dirty 联动通过测试；
- [ ] 前端测试和 build 通过。

---

## 阶段 3：Wails 受管进程、API ready 和清理

### 目标

由 `config-tool` 启动唯一受管 DataFactory 实例，传入 API 参数，等待真正 ready，并在停止或应用退出时清理。

### 前置阅读

```text
config-tool/internal/bindings/system.go
config-tool/internal/app/lifecycle.go
config-tool/internal/app/container.go
config-tool/main.go
standalone_main.py 的 argparse 和 --api 启动段
debug_gui/internal/engine/proc.go             仅作参考，不复制成第二套实现
```

### 主要修改范围

```text
config-tool/internal/bindings/system.go
config-tool/internal/bindings/system_test.go
config-tool/internal/app/lifecycle.go
config-tool/frontend/src/features/templates/RuntimeToolbar.tsx
config-tool/frontend/src/features/templates/useTemplateStore.ts
config-tool/frontend/src/lib/api.ts
```

### 必做动作

1. 按仓库契约第 8 节扩展 StartParams/SystemStatus。
2. 把命令参数构造抽为可测试的纯函数；断言包含 `--api`、`--api-host`、`--api-port`、`--name`。
3. 明确区分 OPC UA `port` 和 HTTP `apiPort`。
4. 启动后轮询 `/api/status`，未 ready 不返回运行成功。
5. 收集 stdout/stderr 最近日志；子进程提前退出时返回退出码和错误。
6. 同时只允许一个受管实时进程。
7. Stop 先优雅等待，再超时强杀；重复 Stop 返回可理解状态，不让 UI 卡死。
8. Wails OnShutdown 清理子进程。
9. UI 实现 `STOPPED_EDITING → STARTING → SIMULATION_RUNNING/ERROR`，ready 前不能显示运行中。
10. 记录 `runningConfigIdentity = path + hash + startedAt`，之后保存 draft 不得修改它。

### Go 测试策略

不要在单元测试里依赖真实 DataFactory.exe。通过注入 command factory、HTTP readiness checker 或测试辅助进程覆盖：

- 参数列表；
- 重复启动；
- ready 成功；
- ready 超时清理；
- 子进程提前退出；
- stderr/exit code 返回；
- Stop 释放进程；
- Shutdown 清理；
- Unicode YAML 绝对路径。

### 退出门禁

- [ ] 实际启动参数完整且端口不混淆；
- [ ] ready 前 UI 为 STARTING；
- [ ] 超时和提前退出无残留进程；
- [ ] running identity 与 saved/draft 独立；
- [ ] Go 进程测试和 Wails build 通过；
- [ ] 没有把 debug_gui 变成第二用户入口。

---

## 阶段 4：REST、WebSocket 和真实现场快照

### 目标

接入 status/meta/snapshot/WebSocket；运行状态下 SVG、检查器和 store 使用 Engine 真实值，并正确处理心跳、过期和重连。

### 前置阅读

```text
datacenter/engine_api.py
controller/engine.py 的 _step_once/_build_complete_snapshot/get_variable_meta
standalone_main.py 的 EngineBinding 注入和 on_snapshot
debug_gui/frontend/src/store/useStore.ts
debug_gui/frontend/src/components/ChartPanel.tsx
```

### 建议新增文件

```text
config-tool/frontend/src/features/runtime/types.ts
config-tool/frontend/src/features/runtime/runtimeApi.ts
config-tool/frontend/src/features/runtime/useRuntimeStore.ts
config-tool/frontend/src/features/runtime/websocket.ts
config-tool/frontend/src/features/runtime/trendBuffer.ts
config-tool/frontend/src/features/runtime/*.test.ts
```

### 必做动作

1. status 获取真实 runtimeName，再调用 meta/snapshot。
2. WebSocket 正常消息替换 latestSnapshot，并追加真实趋势点；心跳只更新时间。
3. 断开后冻结最后值，设置 stale，不清空现场值。
4. 指数退避重连；重连后先 GET snapshot。
5. 修正 broadcaster 慢消费者策略，使 Engine 永不因 UI 阻塞。
6. SVG 在运行态只读取 latestSnapshot；停止态只读取 draft 初值。用单个选择函数明确数据来源。
7. 液位填充按 `level/height` 裁剪到 `[0,1]`；数值仍显示真实 snapshot，越界或缺失显示告警。
8. 阀门使用 `current_opening`，过程流动动画仅在真实流量大于阈值且 snapshot 新鲜时启用。
9. 检查器运行页显示 snapshot 位号和更新时间；缺字段显示 `—` 和明确告警，禁止回退到假默认值。

### 测试

- API status/meta/snapshot 的 runtimeName 语义；
- snapshot 包含契约必需位号；
- 心跳不进入趋势；
- stale 阈值；
- 断线冻结；
- 重连先 REST 后 WS；
- 停止态与运行态数据源切换；
- 阀门使用 current 而非 target；
- Tank 液位来自 snapshot；
- 多 WS 客户端不触发 Engine 重复计算。

### 退出门禁

- [ ] 现场图没有假实时值；
- [ ] 心跳、断线、过期和重连可测试；
- [ ] status 的 runtimeName 没有与 pid2 混淆；
- [ ] snapshot 缺失不会静默伪造；
- [ ] Python API 测试、前端测试和 build 通过。

---

## 阶段 5：原子在线写值和调参写回 DSL

### 目标

实现一次请求提交多个 PID 参数，在同一周期边界应用；提供 PID 面板、事件确认和白名单写回。

### 前置阅读

```text
components/programs/pid.py
controller/engine.py 的 pending changes 和 external overrides
datacenter/engine_api.py 的现有 params/override
todo/second_order_tank_repository_contracts.md 第 5.4、9.2 节
```

### 建议修改/新增

```text
controller/engine.py
datacenter/engine_api.py
tests/test_engine_atomic_writes.py
tests/test_engine_api.py
config-tool/frontend/src/features/templates/PidFaceplate.tsx
config-tool/frontend/src/features/runtime/runtimeApi.ts
config-tool/frontend/src/features/templates/useTemplateStore.ts
```

### 必做动作

1. 在 Engine 增加整批入队方法；验证完成后一次持锁追加批次。
2. `_step_once()` 在一个周期边界应用整批，不能让 REST 循环多次请求。
3. 新增 `/writes`，按契约整批验证、整批成功或整批失败。
4. 不再让模板使用有命名歧义的旧 `/params`；保留旧路由兼容已有调用，除非有测试证明可以安全修正。
5. 后端依据真实 PID 实例和白名单验证 tag；拒绝派生 `AUTO/CAS`、只读 `PV` 和未知字段。
6. PID 面板：AUTO 启用 SV、禁用 MV；MAN 启用 MV；CAS 明确显示 CSV 为当前有效给定。
7. PB/TI/TD/KD 支持一次提交。
8. REST 成功后事件标 pending；只有 snapshot 观察到目标值后标 applied。
9. 在线调参保存在 `runtimeOverrides`，不直接修改 draft。
10. “保存当前调参到 DSL”只同步白名单；MV 需要显式勾选且仅作为初始 MV；禁止写回 PV、当前液位、当前阀位和派生字段。
11. 写回前再次执行模板校验，成功保存后重新加载 saved；当前运行实例仍保持原 running identity，直到重启。

### Python 测试

- PB/TI/TD 同批在同一周期生效；
- 任一非法 tag 导致整批零写入；
- runtimeName 与 `pid2` 正确分离；
- SV 下一 snapshot 生效；
- MAN 下 MV 生效；
- AUTO 下 MV 被拒绝或按明确策略不可写；
- 派生和只读字段拒绝；
- NaN/Inf 拒绝；
- 并发请求不拆散单个批次。

### 前端测试

- MODE 切换启用正确输入；
- 批量提交只有一次 HTTP 请求；
- pending/applied/failed 事件状态；
- snapshot 确认前不显示为已应用；
- DSL 写回白名单；
- MV 默认不写回。

### 退出门禁

- [ ] 原子写值有 Engine 和 API 测试；
- [ ] runtimeName/programName 不混淆；
- [ ] UI 状态由 snapshot 最终确认；
- [ ] 写回不污染动态状态；
- [ ] 在线保存后 saved 与 running 差异显示正确；
- [ ] Python、前端、Go 回归通过。

---

## 阶段 6：趋势、事件和控制品质

### 目标

完成实时趋势、上一轮对照、参数事件和基础控制品质指标。

### 前置阅读

```text
config-tool/frontend/src/components/SimulationPanel.tsx
debug_gui/frontend/src/components/ChartPanel.tsx
config-tool/frontend/src/features/runtime/trendBuffer.ts
todo/second_order_tank_repository_contracts.md 第 10 节
```

### 建议文件

```text
config-tool/frontend/src/features/templates/RuntimeTrendPanel.tsx
config-tool/frontend/src/features/runtime/controlQuality.ts
config-tool/frontend/src/features/runtime/downsample.ts
对应 *.test.ts / *.test.tsx
```

### 必做动作

1. 环形缓冲最多 1200 个真实 snapshot，容量可配置但有上限。
2. 默认液位/SV 左轴，MV/阀位右轴；曲线可开关。
3. 明确 `pid2.PV ← tank_2.level`，避免重复绘制却隐藏绑定关系。
4. 重启仿真时保存一轮灰色 previousRunSeries；停止不自动清空。
5. 显示 pending/applied/failed 调参事件，带时间、旧值、新值和来源。
6. 实现误差带、超调、稳态误差、稳定时间、MV 饱和时间、液位上下限触碰次数。
7. 参数变化后当前指标重新计时，上一段结果保留。
8. stale 时停止追加和动画，图表保留历史。

### 测试

- 环形缓冲容量与顺序；
- 心跳不入图；
- 双轴分组；
- previous run 归档；
- 事件时间与应用确认；
- 60 s 稳定窗口；
- 参数事件后指标重置；
- stale 不追加。

### 退出门禁

- [ ] 长时间运行不会无限增长内存；
- [ ] 上一轮对照和事件真实可见；
- [ ] 指标有纯函数测试；
- [ ] stale 不继续伪动画；
- [ ] 前端测试和 build 通过。

---

## 阶段 7：批量生成、下采样和 CSV 导出

### 目标

把现有 batch 能力整合到同一模板页面，展示进度/结果，并安全绘制大数据。

### 前置阅读

```text
config-tool/internal/bindings/system.go 的 RunBatch/ExportBatch
config-tool/frontend/src/components/SimulationPanel.tsx
standalone_main.py 的 --batch/--export
components/export_templates/
```

### 主要修改范围

```text
config-tool/internal/bindings/system.go
config-tool/internal/bindings/system_test.go
config-tool/frontend/src/features/templates/RuntimeToolbar.tsx
config-tool/frontend/src/features/templates/RuntimeTrendPanel.tsx
config-tool/frontend/src/features/runtime/downsample.ts
```

### 必做动作

1. batch 必须使用已保存且与 draft 一致的合法 DSL；若 dirty，提示先保存。
2. 输入周期数或模拟时长、cycle_time、导出路径和位号列。
3. batch 使用 `--batch`，不得逐周期驱动现场 SVG。
4. 不使用仓库固定 `_batch_export.csv` 作为共享临时文件；为每个任务创建唯一临时路径并在明确时机清理。
5. 返回退出码、stderr、CSV 路径、行列数；失败不得显示空成功图。
6. 结果加载后下采样到最多 3000 点，保留首尾和局部极值。
7. CSV 导出使用 `.csv` 文件对话框，不能复用 YAML 保存对话框。
8. BATCH_RUNNING 禁止启动实时进程；已有实时进程时按 UI 规则先停止或阻止 batch。

### 测试

- 2000 周期成功；
- Unicode YAML/CSV 路径；
- 唯一临时文件；
- 退出码和 stderr 传播；
- dirty 阻止 batch；
- 大数据下采样不超过 3000 点且保留极值；
- CSV 表头和行数；
- YAML/CSV 对话框类型正确。

### 退出门禁

- [ ] 同一模板页完成 batch 和导出；
- [ ] 大数据不会全部传给 Recharts；
- [ ] 临时文件无冲突且可清理；
- [ ] 失败不会伪装为成功；
- [ ] Go、前端、Python 相关测试通过。

---

## 阶段 8：全量回归和端到端验收

### 目标

逐项执行原设计第 18.5、19 节，证明组态、保存、仿真、在线写值、实时运行、OPC UA、batch 和退出清理形成真实闭环。

### 必做动作

1. 从干净或已说明的工作区开始，记录 `git status`。
2. 运行全部前端、Go、Python 测试和 Wails build。
3. 使用临时用户方案执行完整端到端，不修改内置模板。
4. 自动化至少覆盖：
   - 打开默认模板和初值；
   - 所有对象可选；
   - 修改 Tank 2 半径、另存、重载；
   - 非法 SV 阻止保存/启动；
   - 保存并仿真，等待 API ready 和真实 snapshot；
   - 在线 SV、PB/TI/TD；
   - snapshot 确认和趋势事件；
   - 调参白名单写回、重启验证；
   - 2000 周期 batch、下采样和 CSV；
   - 实时运行和 OPC UA 外部写 SV 后 UI 更新；
   - 关闭应用无残留受管进程。
5. 网络断开/重连至少有自动化组件测试；可行时做真实 API 断开验证。
6. 检查仓库内没有临时 CSV、临时 YAML、日志、测试缓存或运行配置污染。
7. 对照设计第 19 节 18 条验收标准逐条打勾；任何未通过项明确列出，不能删去。

### 最终命令

```powershell
Set-Location config-tool\frontend
npm.cmd run test:run
npm.cmd run build
Set-Location ..
$env:GOCACHE = Join-Path ([System.IO.Path]::GetTempPath()) 'review3-go-cache'
go test ./...
wails build
Set-Location ..
python -m pytest tests -q
git status --short
```

### 最终退出门禁

- [ ] 原设计第 18.5 节完整场景有证据；
- [ ] 第 19 节 18 条全部通过，或明确报告未通过项；
- [ ] 前端 build、前端 tests、Go tests、Python tests 通过；
- [ ] 没有假数据、核心算法修改或位号改名；
- [ ] 高级 React Flow 视图仍可用；
- [ ] 没有残留子进程和运行时生成文件；
- [ ] 最终回报遵循原设计第 20 节格式。

---

## 发生问题时的最小诊断格式

如果阶段被阻塞，Agent 必须提供：

```text
阻塞阶段：
失败命令/操作：
退出码或 HTTP 状态：
最小错误输出：
相关文件与行号：
设计期望：
当前真实行为：
已尝试的安全检查：
最小修复方案：
修复是否会扩大范围或影响兼容性：
需要用户决定的事项：
```

不得只报告“环境问题”“接口不通”或“测试失败”。
