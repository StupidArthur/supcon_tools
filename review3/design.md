# DataFactory 工程组态与实时运行重构——Agent 设计与实施任务

> 本文可一次性完整下发给 Agent。
> Agent 必须直接完成代码调整、测试、构建和提交，不要拆成多轮规划任务。

---

## 1. 执行要求

### 1.1 工作环境

* 仓库：`G:\github\supcon_tools`
* 分支：`main`
* 直接在当前主工作目录开发，不创建功能分支，不创建额外 worktree。
* 开始前执行 `git status --short`，确认并保护用户已有修改。
* 不得执行：

  * `git reset --hard`
  * `git clean`
  * 自动 `git stash`
  * `git add .`
  * `git add -A`
* 只能按明确文件路径暂存本任务修改。
* 不得修改或提交无关的 `todo/`、`artifacts/`、补丁文件和工作计划文件。

### 1.2 实施原则

1. **一次性完成本文件全部需求**，不要按导航、工程、运行分别等待下一轮指令。
2. 优先复用现有实现，不重新建设已有能力。
3. 不增加本文没有要求的页面、字段、工作流或“优化功能”。
4. 不重构与本任务无关的 DSL 仿真、趋势、报警、归档、日志、生命周期代码。
5. 遇到旧功能不再展示时，优先取消入口和渲染；没有必要时不要删除后端实现。
6. 保持现有实时会话启停、WebSocket generation guard、订阅聚合、断线保值和 stale 判断逻辑。
7. Wails 接口发生变化后必须重新生成绑定，不得手工修改生成文件。
8. 完成后运行本文规定的测试并提交到 `main`。

---

## 2. 当前实现基线

当前顶部只有“DSL 工程”和“实时运行与 UA”两个入口；实时页面内部再渲染“组态、运行、画面”三个子 Tab。

当前工程组态页包含内部工程列表、YAML 来源、实例列表和报警规则。

现有后端已经具备以下可复用能力：

* 工程总体文件为 `project.yaml`；
* 每个工程已有独立 `sources/` 目录；
* YAML 使用 source ID 复制保存；
* 添加 YAML 时先构造候选工程并校验；
* 校验失败时删除刚复制的文件，不修改工程。

现有运行时已经提供参数描述、所属实例、是否可写、是否可强制等元数据，实例详情应直接复用这些数据。

现有输出强制已经明确限定为只影响 UA 输出、不影响引擎计算，可以直接复用 `fixed` 模式。

现有 Engine API 已经支持通过 `/override` 修改运行变量，因此“设置设定值”不需要新建一套引擎写入机制。

---

# 3. 目标界面结构

工具顶部固定显示三个一级 Tab：

```text
组态调试 | 工程组态 | 实时运行
```

不再存在任何实时功能子 Tab。

| Tab  | 对应页面                    | 本次处理                 |
| ---- | ----------------------- | -------------------- |
| 组态调试 | 现有 `DslShell`           | 只修改 Tab 名称，页面和功能不得改动 |
| 工程组态 | 现有 `RealtimeConfigPage` | 按本文重新组织界面和工程打开方式     |
| 实时运行 | 现有 `RealtimeRunPage`    | 按本文重新设计为左右布局         |

### 导航规则

* 三个 Tab 始终位于 `AppNav` 中。
* 切换页面不得卸载或隐藏顶部导航。
* 切换 Tab 不得停止正在运行的实时服务。
* 没有打开实时工程时：

  * “组态调试”照常使用；
  * “工程组态”显示打开和新建入口；
  * “实时运行”显示“请先打开或新建工程”，不得出现单 YAML 旧入口。
* 原 Dashboard 不再作为任何一级或二级导航入口。

### 前端调整位置

重点修改：

```text
frontend/src/App.tsx
frontend/src/features/app/AppNav.tsx
frontend/src/features/app/navigation.ts
frontend/src/features/realtime/RealtimeUaPage.tsx
frontend/src/features/realtime/RealtimeTabs.tsx
```

目标做法：

* 将应用主视图调整为：

  * `dsl`
  * `project-config`
  * `realtime-run`
* `App.tsx` 根据主视图直接渲染：

  * `DslShell`
  * `RealtimeConfigPage`
  * `RealtimeRunPage`
* `RealtimeUaPage` 和 `RealtimeTabs` 不再参与页面渲染。
* 可以保留未引用文件，除非删除不会扩大修改面。
* 旧 `realtime` 或 `system` 导航值统一兼容重定向到 `project-config`。
* 品牌按钮仍返回组态调试首页。

---

# 4. 组态调试

原 Tab：

```text
DSL 工程
```

改名为：

```text
组态调试
```

除 Tab 文案外，禁止修改：

* YAML 打开和编辑；
* 模板加载；
* 离线仿真；
* 仿真画面；
* 趋势和数据展示；
* 数据导出；
* 保存及另存逻辑；
* `DslShell` 内部导航和状态。

该部分只应产生导航测试和文案调整，不得借机重构 DSL 页面。

---

# 5. 工程组态

## 5.1 页面布局

未打开工程：

```text
┌────────────────────────────────────────────┐
│                                            │
│        [打开工程]     [新建工程]           │
│                                            │
└────────────────────────────────────────────┘
```

已打开工程：

```text
┌─────────────────────────────────────────────────────────┐
│ 工程名称：水箱联调工程                                   │
│ 路径：D:\Projects\水箱联调工程\project.yaml             │
│                                  [打开工程] [新建工程]   │
├─────────────────────────────────────────────────────────┤
│ YAML 文件                                               │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 文件名          │ 副本数 │ 校验结果 │ 操作          │ │
│ ├─────────────────────────────────────────────────────┤ │
│ │ tank.yaml       │   2    │ 通过     │ 移除          │ │
│ │ controller.yaml │   1    │ 通过     │ 移除          │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ [添加 YAML]                                             │
│                                                         │
│ YAML：2 个       展开实例：3 个       校验通过          │
└─────────────────────────────────────────────────────────┘
```

页面只保留：

* 打开工程；
* 新建工程；
* 当前工程名称和本地路径；
* YAML 来源列表；
* 副本数量；
* 添加和移除 YAML；
* 校验摘要和实例总数。

从页面移除：

* 内部工程列表；
* 删除工程按钮；
* 常驻实例列表；
* 实例搜索框；
* 报警规则；
* Dashboard 或画面配置；
* 最近工程列表；
* 工程版本升级入口。

后台实例展开和报警实现可以保留，但本页面不得渲染。

---

## 5.2 工程本地存储

需求只规定“工程总体文件 + 复制后的 YAML”，没有要求改成 JSON。现有代码已经使用 `project.yaml`，因此继续沿用，禁止为了文件扩展名重写序列化。

工程结构：

```text
用户选择的父目录/
└── 工程名称/
    ├── project.yaml
    └── sources/
        ├── <source-id-1>.yaml
        └── <source-id-2>.yaml
```

`project.yaml` 继续使用现有 `Project` 和 `Source` 模型，并新增实时运行默认参数：

```yaml
version: 1
id: "<uuid>"
name: "水箱联调工程"

sources:
  - id: "<source-uuid>"
    name: "tank.yaml"
    file: "sources/<source-uuid>.yaml"
    replicas: 2

runtime:
  cycle_time: 0.5
  opcua_host: "0.0.0.0"
  opcua_port: 18951
```

约束：

* `sources[].name` 保存原始文件名，仅用于显示。
* `sources[].file` 只能是工程内相对路径。
* 不得将外部 YAML 的绝对路径写入工程文件。
* 工程目录移动到其他机器后应仍可打开。
* 外部 YAML 修改或删除后，不得影响工程。
* 基础模板升级后，不得自动更新已有工程。
* 不增加自动同步、自动升级或模板迁移功能。
* 保持现有原子写文件方式。
* 成功的添加、移除和副本数修改继续立即落盘，不新增前端草稿、撤销栈或版本管理。

---

## 5.3 新建工程

交互：

1. 用户点击“新建工程”；
2. 显示现有风格的名称输入对话框；
3. 用户输入工程名称并确认；
4. 打开目录选择器，选择工程父目录；
5. 创建 `<父目录>/<工程名称>/`；
6. 创建 `project.yaml` 和 `sources/`；
7. 将新工程设为当前工程；
8. 页面显示空 YAML 列表。

校验：

* 工程名称去除首尾空格后不能为空；
* 拒绝 Windows 非法文件名字符；
* 目标工程目录已存在且非空时，拒绝创建；
* 用户取消名称输入或目录选择时，不修改当前工程；
* 创建失败时不得留下不完整 `project.yaml`。

不要自动添加模板或默认 YAML。

---

## 5.4 打开工程

交互：

1. 用户点击“打开工程”；
2. 打开文件选择器；
3. 用户选择本地 `project.yaml`；
4. 后端解析工程文件；
5. 检查所有 `sources[].file`；
6. 使用现有编译器执行工程校验；
7. 成功后切换当前工程；
8. 失败时保留原当前工程，并显示具体错误。

必须检查：

* 文件可以读取；
* YAML 可以解析为工程总体结构；
* 工程 ID 和名称有效；
* source ID 有效；
* source 文件位于工程目录内；
* source 文件存在；
* 副本数在现有限制内；
* 实例展开无冲突。

不扫描 `%UserConfigDir%\DataFactory\realtime_projects`，不再通过内部工程列表打开工程。

---

## 5.5 后端路径管理设计

当前 Manager 的业务 API以 `projectID` 为参数，运行和编译也依赖该 ID。为减少改动，继续保留 ID API，不要把全部调用改成路径参数。

在 `realtime.Manager` 中增加运行期位置注册：

```go
type Manager struct {
    storage   *ProjectStorage
    compiler  RealtimeCompiler
    mu        sync.Mutex
    locations map[string]string // projectID -> project.yaml 绝对路径
}
```

新增或调整能力：

```go
CreateProjectAt(ctx, name, parentDir)
OpenProjectFile(ctx, projectFile)
resolveProjectFile(projectID)
```

行为：

* 新建或打开成功后，将 `projectID -> project.yaml` 注册到 `locations`。
* 后续 `AddSource`、`RemoveSource`、`UpdateReplicas`、`ValidateProject`、`CompileProject`、`RuntimeRevision` 继续使用 project ID。
* Manager 内部先解析出当前工程文件和工程目录，再调用 Storage。
* 项目绝对路径只存在于当前应用内存或返回给前端的非持久化字段中，不写入 `project.yaml`。
* 可以保留原 `ListProjects`、`DeleteProject` 等接口供旧测试兼容，但新页面不得调用它们。
* 不实现最近工程持久化。

建议在返回模型中增加非 YAML 字段：

```go
ProjectFile string `json:"projectFile" yaml:"-"`
ProjectDir  string `json:"projectDir" yaml:"-"`
```

也可以使用独立的 `OpenedProject` 返回类型。选择对现有调用改动最小的方式。

重点涉及：

```text
internal/app/container.go
internal/bindings/realtime_project.go
internal/realtime/manager.go
internal/realtime/storage.go
internal/realtime/models.go
frontend/src/lib/api.ts
frontend/src/features/realtime/types.ts
frontend/src/features/realtime/useRealtimeProjectStore.ts
frontend/src/features/realtime/CreateRealtimeProjectDialog.tsx
frontend/src/features/realtime/RealtimeConfigPage.tsx
```

---

## 5.6 添加 YAML 与位号重名校验

添加流程必须保持事务性：

```text
选择外部 YAML
→ 复制到临时/候选 source 路径
→ 用正式 DSL Parser 和实时工程编译器校验
→ 校验通过
→ 更新 project.yaml
```

失败时：

```text
删除候选 source 文件
→ 保持 project.yaml 不变
→ 保持当前 YAML 列表不变
→ 显示冲突详情
```

现有 `Manager.AddSource` 已经具备候选、校验和回滚结构，应直接扩展或复用，不得新写第二套 YAML 解析器。

位号唯一性采用运行时最终命名空间：

```text
实例名.参数名
```

现有实时编译器已经检查展开后的实例名全局唯一性；实例名重复意味着整组 UA 位号命名空间重复。应继续以正式编译器结果为权威，不用正则表达式扫描原始 YAML 文本。

必须覆盖：

* 新 YAML 内部存在重复实例名；
* 新 YAML 与工程已有 YAML 存在重复实例名；
* 副本展开后产生名称冲突。

冲突提示示例：

```text
无法添加 tank.yaml

发现位号命名空间重名：
- tank_1
  - tank.yaml
  - existing.yaml
- pid_1
  - tank.yaml 内部重复
```

提示必须列出全部冲突名称和来源文件，不能只显示“校验失败”。

---

# 6. 实时运行

## 6.1 页面布局

```text
┌───────────────────┬────────────────────────────────────────┐
│ 运行控制           │ 实例列表                               │
│                   │                                        │
│ 控制周期           │ 实例名 │ 画面模板 │ 详情              │
│ UA 地址            │                                        │
│ UA 端口            │                                        │
│                   │                                        │
│ 当前状态           │                                        │
│ [启动] / [停止]    │                                        │
└───────────────────┴────────────────────────────────────────┘
```

要求：

* 页面使用左右布局；
* 左侧固定宽度，右侧占剩余空间；
* 不使用子 Tab；
* 不渲染纵向长页面；
* 不渲染单 YAML 旧入口；
* 不渲染趋势、报警、运行历史和日志；
* 不渲染独立 Dashboard；
* 保留这些功能的现有代码，除非删除引用是编译所必需。

当前运行页中的会话启动、Token 获取、WebSocket 启动及 generation guard 必须从原页面完整保留，不能因重新布局而简化或删除。

---

## 6.2 左侧运行控制

字段：

| 字段    |       默认值 | 说明                     |
| ----- | --------: | ---------------------- |
| 控制周期  |   `0.5` 秒 | 传入 Engine `cycle_time` |
| UA 地址 | `0.0.0.0` | OPC UA Server 监听地址     |
| UA 端口 |   `18951` | OPC UA Server 监听端口     |
| 当前状态  |       未运行 | 显示启动、运行、停止或失败          |
| 启动/停止 |         — | 控制当前工程整体运行             |

不再向用户暴露：

* REST Host；
* REST/WS 端口；
* 高级端口配置。

REST/WS 继续使用现有内部默认配置，只作为应用内部调试通道。

### 启动

1. 必须存在当前工程；
2. 重新执行工程校验；
3. 校验失败则禁止启动；
4. 使用当前工程 ID 启动工程；
5. 将控制周期、UA 地址、UA 端口传入运行参数；
6. 启动成功后锁定三个输入框；
7. 建立现有 REST/WS 会话；
8. 按现有逻辑获取 Token 和 tag catalog。

保持现有约束：

* 离线仿真或批量任务运行时禁止启动实时工程；
* 已有实时进程运行时禁止重复启动；
* 启动失败应显示现有后端错误；
* 切换顶部 Tab 不停止服务。

### 停止

继续使用现有 `RealtimeRuntimeBinding.Stop` 完整事务，不修改已经完成的并发停止、归档停止和异常退出收口。

UI 只调用现有 session store 的停止方法，不直接调用底层 System stop。

---

## 6.3 UA 地址传递

当前启动参数只有 OPC UA 端口，OPC UA Server 地址固定生成成 `0.0.0.0`。

需要沿现有启动链增加 `opcUaHost`：

```text
前端运行表单
→ RealtimeStartOptions
→ RealtimeRunSession
→ SystemBinding.StartParams
→ BuildArgs
→ standalone_main.py --opcua-host
→ opc.tcp://<host>:<port>
```

修改内容：

### Go

```go
type RealtimeStartOptions struct {
    CycleTime float64 `json:"cycleTime"`
    OPCUAHost string  `json:"opcUaHost"`
    OPCUAPort int     `json:"opcUaPort"`
    // 保留现有内部 API 字段
}
```

```go
type StartParams struct {
    OPCUAHost string `json:"opcUaHost"`
    Port      int    `json:"port"`
}
```

`BuildArgs` 增加：

```text
--opcua-host <host>
```

### Python

`standalone_main.py` 增加：

```python
parser.add_argument("--opcua-host", default="0.0.0.0")
```

生成：

```python
server_url = f"opc.tcp://{args.opcua_host}:{port}"
```

不要修改 `OPCUAServerConfig` 的其他行为。

---

## 6.4 右侧实例列表

数据直接来自工程校验结果 `ExpandedInstance[]`，不重新解析 YAML。

表格只包含三列：

| 列    | 数据来源                                                  |
| ---- | ----------------------------------------------------- |
| 实例名  | `ExpandedInstance.name`                               |
| 画面模板 | `sourceId -> RealtimeSource.name`，即该实例来源的工程内 YAML 文件名 |
| 详情   | 打开该实例参数详情                                             |

“画面模板”在本阶段只是来源模板标识：

* 不新增画面编辑器；
* 不新增 Dashboard 绑定；
* 不新增模板选择框；
* 不保存额外画面配置；
* 不恢复原独立“画面”页面。

未运行时仍显示实例列表，但“详情”点击后显示：

```text
服务尚未启动，暂无实时参数。
```

---

# 7. 实例详情

## 7.1 打开方式

点击实例的“详情”后，右侧区域切换为详情视图：

```text
┌──────────────────────────────────────────────────────────┐
│ [← 返回实例列表]               当前实例：tank_1          │
├──────────────────────────────────────────────────────────┤
│ 参数名 │ 描述 │ 实时值 │ 操作                           │
├──────────────────────────────────────────────────────────┤
│ level  │ 液位 │ 1.234  │ [选择操作 ▼]                  │
│ inlet  │ 入口 │ 0.500  │ [选择操作 ▼]                  │
└──────────────────────────────────────────────────────────┘
```

不得：

* 打开新的顶部 Tab；
* 打开新窗口；
* 跳转到 Dashboard；
* 显示整个工程所有位号。

## 7.2 参数筛选和订阅

运行后，从现有 `tagCatalog` 中筛选：

```typescript
tag.instance === selectedInstance.name
```

参数显示：

| 列   | 数据                                 |
| --- | ---------------------------------- |
| 参数名 | `tag.attribute`，缺失时使用完整 `tag.name` |
| 描述  | `tag.description`                  |
| 实时值 | `latestFrame.values[tag.name]`     |
| 操作  | 本文定义的下拉操作及当前干预状态                   |

规则：

* 实时值是引擎内部运行值，不是被固定后的 UA 输出值；
* 缺失值显示 `—`，不得替换为 `0`；
* 数据断开或过期时保留最后值，并显示现有连接或过期状态；
* 详情打开时，只订阅当前实例参数；
* 使用现有 `registerSubscription` 注册独立 source，例如 `instance-detail`；
* 返回实例列表或组件卸载时注销该订阅；
* 不订阅完整 50,000 位号目录。

---

# 8. 参数操作

操作列使用一个下拉列表，菜单只包含三个业务动作：

```text
固定 UA 输出值
设置设定值
修改 UA 质量码
```

不要恢复原来的 `H / 0 / F` 小按钮，不提供持续时间、置零和保持模式入口。

选择操作后使用项目现有样式的对话框或行内弹层，不使用 `window.prompt`。

---

## 8.1 固定 UA 输出值

交互：

1. 用户选择“固定 UA 输出值”；
2. 输入有限数值；
3. 确认；
4. 调用现有 force API：

```text
mode = fixed
value = 用户输入值
duration = null
```

语义：

* Engine 算法继续运行；
* 详情表中的实时值继续变化；
* OPC UA 对外输出固定为指定值；
* 干预只在当前运行会话内有效；
* 停止进程后自然清空；
* 不写入工程文件。

操作单元格显示：

```text
固定输出：10.0  [解除]
```

“解除”调用现有 `ClearForce`，恢复正常跟随。

---

## 8.2 设置设定值

交互：

1. 用户选择“设置设定值”；
2. 数值输入框默认值为 `0`；
3. 用户修改并确认；
4. 调用现有 Engine `/override` 能力写入完整 tag 名。

语义：

* 写入 Engine 运行变量；
* 新值参与后续算法运算；
* 不属于 UA 输出强制；
* 不写入工程 YAML；
* 不提供“恢复旧值”功能。

能力限制：

* 只有 `tag.writable === true` 时可执行；
* 不可写参数的菜单项禁用；
* 失败时显示后端原始错误；
* 成功时显示简短成功状态，不增加操作历史页面。

不要新建第二套设定值队列；复用现有 `engine.override_variable` 或现有原子写能力。

---

## 8.3 修改 UA 质量码

当前代码没有完整的质量码覆盖能力，需要实现最小闭环。

本阶段只支持：

```text
Good
Uncertain
Bad
```

不得增加自定义数值状态码编辑器或完整 OPC UA 状态码浏览器。

### Python 数据层

在现有 `ForceManager` 中增加独立质量码覆盖状态：

```python
_quality_overrides: Dict[str, str]
```

增加方法：

```python
set_quality(tag, quality)
clear_quality(tag)
snapshot_qualities()
```

要求：

* 与固定值状态彼此独立；
* 同一 tag 可以同时固定值和覆盖质量码；
* 使用现有有效 UA tag 集合校验；
* 状态只在当前进程内存在；
* 线程安全继续使用现有锁。

### Engine API

增加最小 REST 接口：

```text
POST   /api/quality
DELETE /api/quality/{tag}
GET    /api/quality
```

请求：

```json
{
  "tag": "tank_1.level",
  "quality": "Bad"
}
```

非法 tag 或非法 quality 返回 HTTP 400。

### OPC UA Server

在每次写节点时：

* 值继续取正常值或 force 后的固定值；
* quality override 存在时写对应 `StatusCode`；
* 不存在时写 `Good`；
* 清除 quality 后，下一个更新周期恢复 `Good`；
* 质量码覆盖不得改变共享内存值和 Engine snapshot。

### Go Binding

在 `RealtimeProjectBinding` 中增加：

```go
SetQuality(...)
ClearQuality(...)
GetQualities(...)
SetRuntimeValue(...) // 包装现有 /override
```

所有请求继续使用当前 API Token 鉴权。

检查并统一现有 force GET/DELETE 请求的鉴权方式；本任务新增操作必须在正常鉴权模式下可用。

### 前端

操作单元格显示：

```text
质量码：Bad  [解除]
```

解除只清除质量码覆盖，不清除固定 UA 输出。

---

# 9. 前端组件设计

建议拆分，但不要建立新的大型框架：

```text
RealtimeRunPage
├── RuntimeControlPanel
├── RuntimeInstanceTable
└── RuntimeInstanceDetail
    └── RuntimeParameterActionDialog
```

允许将组件保留在同一文件中，只要代码清晰、测试可定位。不要为了目录整洁进行无关文件迁移。

`RealtimeRunPage` 保留以下现有逻辑：

* `dfStatus`；
* offline/batch 互斥；
* session refresh；
* startProject；
* stopSession；
* Runtime token bootstrap；
* `useRuntimeStore.connect/disconnect`；
* config revision warning；
  -错误处理。

删除该页面的以下依赖和渲染：

```text
useDslProjectStore
startSingleYaml
openDsl
RuntimeTagTable 的全工程平铺用法
GenericTrendPanel
AlarmPanel
RunHistoryPanel
日志长列表
高级 REST 端口配置
```

`RuntimeTagTable` 可以：

* 改造成实例详情表并复用；
* 或保留旧组件、新建 `RuntimeInstanceDetail`。

选择改动和回归风险较小的方式。不得同时保留两套用户入口。

---

# 10. Store 与 API 调整

## 10.1 `useRealtimeProjectStore`

移除页面所需之外的状态：

```typescript
projects
refreshProjects
deleteProject
```

可以为了兼容暂时保留接口，但新 UI 不得依赖。

当前 store 至少维护：

```typescript
currentProject
instances
duplicates
loading
error
createProject(name)
openProject()
addSource(projectId)
removeSource(projectId, sourceId)
updateReplicas(projectId, sourceId, replicas)
validateCurrentProject()
```

`openProject()` 不再接受工程 ID，由 Wails 文件选择器返回选中的本地工程。

## 10.2 运行参数

项目类型增加：

```typescript
interface RealtimeRuntimeOptions {
  cycleTime: number
  opcUaHost: string
  opcUaPort: number
}
```

打开工程时加载默认值。用户修改后的值至少在启动前写回当前工程总体文件。

不要将内部 API Token、REST Host、REST 端口写入工程文件。

---

# 11. 明确禁止的额外功能

Agent 不得实现：

* DSL 页面重构；
* 独立画面页面；
* Dashboard 编辑器重构；
* 实例画面模板配置器；
* 报警规则新入口；
* 趋势新入口；
* 日志新入口；
* 运行历史新入口；
* 最近工程；
* 自动保存历史版本；
* 撤销/重做；
* 工程导入导出压缩包；
* 工程模板升级；
* 自动同步外部 YAML；
* 多工程同时运行；
* 自动分配端口；
* 自定义 OPC UA 状态码；
* force 持续时间；
* 批量参数操作；
* UI 主题重做；
* 与本需求无关的代码清理。

---

# 12. 实施顺序

Agent 在一次任务中依次完成，不要中途请求下一阶段指令：

1. 检查工作区并阅读现有相关测试。
2. 调整顶层导航和 App 主视图。
3. 将工程存储改为用户选择的本地工程目录。
4. 调整工程组态 Store、Wails API 和页面。
5. 保留并补强添加 YAML 的事务式重名校验。
6. 增加 `opcUaHost` 启动参数完整传递链。
7. 重构实时运行页面布局。
8. 实现实例列表和实例详情订阅。
9. 接入固定 UA 输出。
10. 接入现有设定值写入。
11. 实现最小质量码覆盖闭环。
12. 更新 Wails 生成绑定。
13. 更新或新增测试。
14. 运行完整测试和构建。
15. 仅暂存本任务文件并提交。

不要为每一步创建单独的 Agent 任务。

---

# 13. 测试要求

## 13.1 前端

至少覆盖：

* 顶部显示三个准确文案；
* 不渲染实时子 Tab；
* “组态调试”仍渲染原 DslShell；
* 未打开工程时显示打开、新建两个按钮；
* 打开和新建调用不同 API；
* 页面不显示实例列表和报警规则；
* 添加重名 YAML 时列表不变化并显示冲突；
* 实时运行页面为左右布局；
* 不显示单 YAML、趋势、报警、历史和日志；
* 实例列表只有规定三列；
* 点击详情按 instance 筛选 tag；
* 缺失实时值显示 `—`；
* 固定输出调用 `fixed` 且不传 duration；
* 设定值输入默认 `0`；
* 质量码只能选择 Good、Uncertain、Bad；
* 返回实例列表后注销详情订阅；
* 切换顶部 Tab 不调用 stop。

命令：

```powershell
cd G:\github\supcon_tools\review3\config-tool\frontend
npm run test:run
npm run build
```

## 13.2 Go

至少覆盖：

* 在用户指定目录创建工程；
* 打开任意合法本地 `project.yaml`；
* source 路径解析以工程目录为基准；
* 外部原 YAML 删除后工程仍可使用；
* 添加重名 YAML 后：

  * `project.yaml` 未变化；
  * `sources/` 无残留候选文件；
  * 当前工程模型未变化；
* `opcUaHost` 正确进入 `BuildArgs`；
* 新运行参数正确进入 session；
* 新 REST Binding 正确带 Token；
* 现有停止生命周期测试继续通过。

命令：

```powershell
cd G:\github\supcon_tools\review3\config-tool
go test ./...
go test -race ./...
```

## 13.3 Python

至少覆盖：

* 同一 YAML 内实例重名；
* 新 YAML 与已有 YAML 实例重名；
* 副本展开后重名；
* `--opcua-host` 正确生成 endpoint；
* fixed 只改变输出；
* quality 不改变数值；
* fixed 与 quality 可以同时生效；
* 清除 quality 后恢复 Good；
* 非法 tag 和非法 quality 被拒绝；
* `/override` 继续修改 Engine 变量。

命令：

```powershell
cd G:\github\supcon_tools\review3
python -m pytest -q
```

## 13.4 最终构建

```powershell
cd G:\github\supcon_tools\review3\config-tool
wails build
```

必须确认：

* Wails 绑定已更新；
* TypeScript 无错误；
* Go 测试及 race 通过；
* Python 测试通过；
* Windows EXE 构建成功；
* 没有把构建产物、日志或测试临时文件提交到 Git。

---

# 14. 验收矩阵

| 编号  | 验收内容                             |
| --- | -------------------------------- |
| A1  | 顶部只有“组态调试、工程组态、实时运行”三个 Tab       |
| A2  | 原 DSL 功能除名称外没有行为变化               |
| A3  | 不再存在实时子 Tab 和独立画面入口              |
| B1  | 工程组态有独立“打开工程”和“新建工程”按钮           |
| B2  | 工程保存在用户选择的本地目录                   |
| B3  | 工程包含 `project.yaml` 和 `sources/` |
| B4  | 添加的 YAML 被复制到工程目录，不引用外部原文件       |
| B5  | 模板或外部文件变化不影响已有工程                 |
| B6  | 组态页不显示实例列表和报警规则                  |
| B7  | 位号命名空间重名时整个 YAML 添加失败且无文件残留      |
| C1  | 实时运行页为左控制、右实例布局                  |
| C2  | 左侧只暴露周期、UA 地址、UA 端口和启停           |
| C3  | 实例表只显示实例名、画面模板和详情                |
| C4  | 详情表只显示参数名、描述、实时值和操作              |
| C5  | 固定 UA 输出不停止或修改内部算法值              |
| C6  | 设定值写入 Engine，并默认输入 `0`           |
| C7  | 质量码覆盖不修改数值                       |
| C8  | fixed 和 quality 状态能够分别解除         |
| C9  | 页面切换不停止实时服务                      |
| C10 | 现有运行生命周期、断线和订阅机制没有回归             |

---

# 15. Agent 最终回复格式

完成后只报告以下内容，不写大段设计复述：

```text
实现结果
- 导航：
- 工程组态：
- 实时运行：
- 运行时操作：

主要修改文件
- ...

测试结果
- Frontend:
- Go:
- Go race:
- Python:
- Wails build:

提交
- Commit:
- 工作区剩余未提交内容：
```

如果存在未完成项，必须明确写出具体文件、原因和阻塞条件，不得用“后续可优化”代替。
