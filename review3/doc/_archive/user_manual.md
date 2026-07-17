# Data Factory Next 用户手册

## 1. 快速启动

### 1.1 环境准备
- 安装 Python 3.10+
- 运行 Redis 服务器 (默认端口 6379)
- 安装依赖：`pip install -r requirements.txt`

### 1.2 启动服务

系统采用 Web 后端驱动模式，启动后端会自动拉起 `ServiceManager` 及其管理的多个引擎实例（Simulation/Playback）、状态存储服务和 OPC UA 服务。

**一键快速启动 (推荐):**
在 Windows 环境下，您可以直接双击运行项目中的便捷脚本，它将自动开启两个独立窗口分别运行前后端：
```bash
# 双击运行
tests\run_all.bat
```

**手动分步启动:**

**A. 启动后端 (API + 所有服务):**
```bash
# 确保在项目根目录下
python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000
```

**B. 启动前端 (管理界面):**
```bash
cd web_frontend
# 如果是第一次运行，请先安装依赖
# npm install
npm run dev
```
访问 `http://localhost:5173` 即可进入管理后台。

## 2. 配置说明

### 2.1 多引擎配置 (`engines_manifest.yaml`)
在项目配置目录下创建 `engines_manifest.yaml` 来编排引擎：
```yaml
instances:
  - id: engine_vibration_01    # 引擎唯一标识
    type: simulation           # 类型：simulation 或 playback
    source: vibration.yaml     # 关联的 DSL 组态文件
  
  - id: engine_historical_replay
    type: playback
    file_path: history.xlsx    # 回放源文件路径
    time_col: "Timestamp"      # 时间参考列
```

## 3. 功能使用

### 3.1 实时监控
访问 Web 控制面板（默认 `http://localhost:3000`）：
- **服务诊断**：在“服务诊断”页面查看各引擎的延迟、内存占用和活跃状态。
- **实时数据**：在“实时组态”页面通过三级树结构浏览全量位号。

### 3.2 历史查询
系统产生的历史数据存储在项目根目录外的 `storage/storage_service.duckdb` 中。
可以使用标准 SQL 工具或通过系统的 API 接口进行数据导出和采样查询。

### 3.3 基础设施编排 (引擎管理)
1. 点击顶部导航栏的 **“设置” (引擎管理)** 图标。
2. 在左侧 YAML 编辑器中修改 `engines_manifest.yaml`：
   - 增加 `instances` 项以启动新引擎。
   - 调整 `storage` 或 `opcua` 的周期参数。
3. 点击 **“保存配置”** 将修改持久化到服务器。
4. 点击 **“全量热重载”** (红色按钮) 使配置生效。系统将自动对比状态并完成进程的启停切换。

## 4. 常见问题
- **Q**: 为什么 StorageService 显示 Waiting？
- **A**: 通常是因为没有活跃的 Engine 向 Redis 推送数据或推送间隔超过预期，请检查 Engine 组态是否正确加载。

## 5. 数据模拟与导出列
- 路径：**数据模拟**：默认曲线与默认导出列**仅**来自 DSL **非空** **`display_args`**；未写或空列表的 program 项不参与。**数据生成**在未传 `selected_variables` 时与上述列一致；图表可按 `ref` 缩放纵坐标（仅显示），CSV 为原始值。
- 水箱/阀门示例：`source_flow`（VARIABLE）→ `valve.execute(..., inlet_flow=source_flow)` → `tank.execute(inlet_flow=valve.outlet_flow)`。
