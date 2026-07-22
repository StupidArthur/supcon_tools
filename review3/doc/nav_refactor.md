# DataFactory 导航重构 — 需求 / 设计 / 使用说明

## 需求

工具仅保留两个核心入口：

1. **DSL 工程**：编辑调试 DSL、仿真、Batch、趋势、导出
2. **实时运行与 UA**：已保存 DSL 启动实时实例 + OPC UA

删除一级入口：仿真运行 / 高级组态 / 二阶水箱模板；「系统管理」改名为「实时运行与 UA」。

## 设计

| 表面 | 实现 |
|------|------|
| 顶层导航 | `features/app/AppNav.tsx` + `navigation.ts` |
| 视图状态 | `useCanvasStore.view`: `dsl` \| `realtime`；旧值重定向 |
| DSL 壳 | `features/dsl/DslShell` → Home / Workspace |
| 工程状态 | `useDslProjectStore`（phase / tabs / yaml / recent） |
| draft 仿真 | `materializeDraft.ts` + Go `AllocateTempYAMLPath` / `WriteTempYAML` / `ReadTextFile` / `WriteTextFile` |
| 实时页 | `features/realtime/RealtimeUaPage`（无 exe/模式/配置路径文本框） |

旧路由 `template|simulation|config|system` 经 `setView` 重定向到 `dsl` / `realtime`，避免空白页。

## 使用

1. 启动 `config-tool`（`wails dev` 或 `build/bin/config-tool.exe`）
2. 顶栏：`DataFactory | DSL 工程 | 实时运行与 UA`
3. DSL 首页：新建 / 打开 YAML / 最近 / 模板（单阀门二阶水箱）
4. 工作区：模板视图 | YAML 源码 | 拓扑与诊断；下方仿真控制 | 趋势 | Batch | 导出
5. 仿真控制：校验通过后将当前 draft 写入临时 YAML 启动，不覆盖用户文件
6. 实时运行：仅已保存 DSL；未保存时提示先保存

## 验证说明

- `npm run build`：通过
- `npm run test:acceptance`：除 stage_0 旧 Toolbar 文案（故意删除的一级入口）外通过
- 未改 DSL / 仿真算法 / UA 节点 / 原子写 / acceptance 契约 / 内置 YAML
- 未执行 Git 命令
