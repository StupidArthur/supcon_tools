# AI 新会话必读 — Ray 集群监控工具

> 用途：新开一个 AI 会话时，第一件事读这个文件。
> 最后更新：2026-07-05
> 当前版本：**v0.92**

## 1. 项目是什么

桌面 GUI 工具（Wails v2 + Go + React 18 + TypeScript + SQLite），监控多个独立 Ray 集群（KubeRay 部署）。
v0.92，4 集群 × 18 节点生产在用。

## 2. 必读文档（按这个顺序读）

1. `项目文档.md` — 入口。架构、构建、当前状态、接手要点（11 节）
2. `Ray监控工具设计v2.md` — 当前主设计（多集群 + 告警）
3. `Ray代码审查报告.md` — 12 个已知 bug，3 个高严重度（**先看第 5 节"修复优先级建议"**）
4. `Ray监控标准.md` — 监控方法论（USE/黄金信号/RED）

其他 3 份（`Ray接口探查清单.md`、`Ray监控调研文档.md`、`Ray监控工具设计.md`）是历史版本/调研，除非有特定问题否则不读。

## 3. 当前焦点（未结案）

### 3.1 告警显示问题（最优先）
- 用户最初报告"角标显示 13 条，UI 列表空"
- 根因：`storage.CreateAlert` INSERT 占位符 16 列只给 13 值，告警插不进库
- 修复：补齐占位符（`storage/store.go:300-313` 已修）
- 测试：`storage/alert_test.go:12 TestAlertScan` 验证通过
- **当前状态：修复已就位，用户尚未在新版本验证**

### 3.2 审查报告 3 个高严重度 bug（**必修**）
详见 `Ray代码审查报告.md` 第 3 节：
- **#1** `collector/collector.go:362` — fetch 失败零值覆盖 snapshot
- **#2** `collector/collector.go:327` — 半哑节点 mem 覆盖
- **#5** `storage/store.go:341` — AckAlert 漏写 acknowledge 事件

低/中严重度有 9 个，按报告第 5 节排序。

## 4. 最近完成

### 4.1 HTTP gzip 透明解压（2026-07-03，v0.91 → v0.92 路上）
生产环境 detail tick 带宽 200MB/3s 峰值（4 集群 × 18 节点），加 gzip 预期降到 20-40MB/3s。

**改了 5 个文件 + 重生 Wails 绑定**：
- `collector/ray_client.go` — `Transport.DisableCompression=true` + 手动解压 + 新公开方法 `LastGzipUsed()`
- `model/model.go` — `ClusterMetric.GzipSupported bool`
- `collector/collector.go` — `FetchCluster` 成功后刷 `cm.GzipSupported`
- `frontend/src/components/views/OverviewView.tsx` — PerfCard 加 "HTTP 压缩" 一行
- `collector/collector_test.go` — 3 个 gzip 测试用例（**未跑**，等用户验证）
- `frontend/wailsjs/go/models.ts` — `wails generate module` 重生

**关键设计决策**（不能从代码反推出来）：
- ❌ **gzip 状态不入库**（不写 `cluster_metric` 表）— 只活在内存 `Snapshot.Cluster` 里。设计文档里写了理由。
- ❌ **Go 自动解压不能用** — Go 会解压后剥掉 `Content-Encoding` 头，无法检测。改用 `Transport.DisableCompression=true` + 手动。
- ✅ **检测源用 `FetchCluster`**（不是 `/nodes/{id}`）— 唯一每轮必打的请求，状态最稳定。
- ✅ **`WriteCluster` 不改** — INSERT 9 字段不变，多余的 `GzipSupported` 字段被 SQL 静默忽略。

### 4.2 UX 改造（2026-07-03，v0.91 → v0.92）
3 个改动：

**a. 保存配置不再自动启动**
- 改 `collector/manager.go`：引入 `addClusterWithState` 私有方法；`AddCluster` / `UpdateCluster` / `ReloadAll` 按 cluster ID 继承旧 started 状态
- 新增集群 → 默认停止；已运行的 → 保持运行
- 用户描述"保存配置模式就自动跑"已修复

**b. 集群操作弹窗**
- 新组件 `frontend/src/components/ClusterControlDialog.tsx`
- TopBar 替换"开始/停止全部"切换按钮 → 单一"操作"按钮
- 弹窗内：全部开始 / 全部停止 / 逐集群 start & stop
- App.tsx 加 `showControl` state + modal 渲染

**c. 所有表格列头筛选**
- `utils.ts` → `utils.tsx`（因含 JSX）
- 新增 `FilterInput` 组件 + `applyFilters` helper
- 5 个 view 各加 contains 输入框：NodesView / WorkersView / ActorsView / JobsView / AlertsView（共 6 张表含 Job 历史）
- 配套修小 bug：`ActorsView.tsx` 的 `useEffect` 之前依赖 `actors`（每 5s 变），事件流会频繁重拉 → 改为只依赖 `clusterID`

### 4.3 静态代码审查（2026-07-03）
完整报告见 `Ray代码审查报告.md`。**用户优先要修的：#1 + #2 + #5**（高严重度）。

## 5. 待办

按优先级：

1. **gzip 上生产后实测带宽**（验证 200MB → 20-40MB 预期）
2. **告警显示问题用户验证**（修复后跑一次 16:17 的新包，看 13 条告警是否正常显示）
3. **修审查报告 #1 + #2 + #5**（高严重度）
4. **跑 gzip 3 个新测试**（`go test -count=1 ./collector/...`）
5. **修审查报告剩余 bug**（按报告第 5 节）

## 6. 用户工作风格（重要）

- **先找证据再下结论**，不要预设用户操作出错
- 加诊断让程序自己报告状态（debug.txt、日志），不要猜
- 每个假设要验证（写测试或加日志），不能跳过验证直接改代码
- "需重启采集生效"这类标记必须真正实现重建逻辑，不能只标记
- 项目有自己的 dev-skill 五阶段流程（需求→设计→实现→测试→提交打包），开发工作按这个推

## 7. 环境注意事项

- **每条 bash 前** `export PATH="/d/TDM-GCC-64/bin:$PATH"`（GCC for CGO/WebView2 binding）
- 改 `app.go` 方法签名后必须 `wails generate module`，否则前端调不到
- 项目**不是 git 仓库**，用户不要求时不要 `git init`
- 前端 `api.ts` 用纯 interface（不是 Wails 生成的 `config.Config`），直接用 `setState` 不会缺 convertValues

## 8. 已知未验证 / 待跟进

- [ ] 告警显示问题：v0.91 的 CreateAlert 修复后用户还没在新版验证（v0.92 部署后跑一次）
- [ ] gzip 带宽实测：v0.92 部署到生产后看 200MB → 20-40MB 是否兑现
- [ ] gzip 3 个新测试用例未跑（`go test -count=1 ./collector/...`）
- [ ] `wails generate module` 上次跑有"文件被占"问题（首次失败重试成功），后续如再遇先 `ls frontend/wailsjs/go/` 确认状态
- [ ] `m.belowCnt` map 长期累积（审查 #10）— 跑久了才显现，暂无清理机制

## 9. 读完后

如果用户给的任务在本文件"第 5 节待办"里 → 直接做。
如果是新任务 → 先确认是否在 `Ray代码审查报告.md` 范围内，**避免重复修已经被识别但用户选择暂缓的 bug**。
如果不确定 → 问用户，不要猜。
