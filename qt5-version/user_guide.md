# alg_update 算法管理工具集 用户手册

> 把本地算法文件 / CSV 发布清单 同步到 **alg-manager-web-v2.2-tpt** 算法管理平台，覆盖**同步**、**批量发布**、**重发布**三套日常工作流。
>
> **当前版本**：v1.5（alg_sync） / v1.2（alg_publish） / v1.2（alg_republish） / v1.1（alg_sync_no_edit）
>
> designed by @yuzechao

---

## 1. 这是什么

`alg_update` 是一套围绕 alg-manager 平台（API 前缀 `/alg-manager-web-v2.2-tpt`）的算法管理 GUI 工具集，面向**算法开发者**和**运维**日常面对的三类操作：

- **alg_sync** —— 把本地 `resource/` 目录里的算法 zip/py **重新上传并保持平台已发布状态**不变（全流程：登录 → 拉取平台 → 扫描本地 → 匹配 → 取消发布 → 上传 → 编辑 → 重新发布）
- **alg_publish** —— 用 **CSV 清单**批量调整平台算法的"发布/不发布"+ 核数/副本数/CPU&GPU 类型，并发批量执行
- **alg_republish** —— 对平台所有已发布算法逐个执行"取消发布 → 等 1 秒 → 重新发布"，用于让所有算法实例重新拉起

另外附带：

- **alg_sync_no_edit** —— `alg_sync` 的简化版，跳过 `edit` 步骤（适合只刷包不修改元信息的场景）
- **alg_manager** —— **非 GUI** Python 库，为 FastAPI Web 后端提供算法管理能力（`connect / fetch / load / compare / release_pending / unrelease_misreleased`）

---

## 2. 使用入门

### 2.1 工具集地图

| 子工具 | 用途 | GUI 入口 | CLI / 库入口 | 产物 exe |
|---|---|---|---|---|
| **alg_sync** | 本地算法 zip/py 与平台已发布状态双向同步 | `算法同步工具v1.5.exe` | `python alg_sync/task.py` | `算法同步工具v1.5.exe` |
| **alg_publish** | CSV 驱动的批量发布 / 调整参数 | `算法发布工具v1.2.exe` | — | `算法发布工具v1.2.exe` |
| **alg_republish** | 已发布算法全量取消→1s→重发布 | `算法重发布工具v1.2.exe` | — | `算法重发布工具v1.2.exe` |
| **alg_sync_no_edit** | alg_sync 的轻量版（不上传 edit） | `算法同步工具_不编辑v1.1.exe` | — | `算法同步工具_不编辑v1.1.exe` |
| **alg_manager** | FastAPI 后端用的非 GUI 库 | — | `from alg_update.alg_manager import AlgManager` | — |

四个 GUI 都是基于 PyQt6 + httpx，单文件 PyInstaller 打包，**目标机不需要装 Python**。

### 2.2 平台接入信息

所有子工具都通过 HTTP 调 alg-manager 的接口，URL / 凭据默认如下：

| 字段 | 默认值 | 备注 |
|---|---|---|
| **URL** | `http://10.16.11.1:31501` | alg_publish / alg_sync / alg_republish / alg_sync_no_edit GUI 默认 |
| **Username** | `admin` | 平台管理员账号 |
| **Password** | （空，用户填写） | GUI 的密码框默认空，每次启动要重新填 |
| **Tenant ID** | （空） | 只有 URL 是 `https://` 才会显示该输入框，HTTP 模式不用填 |

> 内部代码里另外出现过的备选 URL：`http://10.16.11.45:31501`（alg_manager.py 默认 / algdevp3.py 旧脚本）、`http://10.16.11.46:31501`（test_* 用）。这些都是历史/测试环境的快照，**以 GUI 默认的 `10.16.11.1:31501` 为准**。

> `api_client / Supcon@1304` 是 `common/api.py` 和 `task.py` 里 CLI 入口硬编码的凭据，**只在用源码跑 CLI 时使用**。GUI 不会用这对默认凭据。

**在哪改**：每个 GUI 的 URL / Username / Password / Tenant ID 都可以在窗口里直接覆盖；不需要改代码。源码里改默认值则分别在：
- `common/api.py`（被 alg_sync / alg_publish / alg_sync_no_edit 共用）
- `alg_republish/api.py`（独立 copy）
- `alg_manager.py`（库的 `AlgManager.__init__`）

### 2.3 支持的操作系统

- **Windows** 10 / 11（64 位）—— PyInstaller 单文件 exe 直接运行
- **Linux**：源码可以跑（参考 2.4），但 PyInstaller 打包产物目前只在 Windows 上验证过

### 2.4 用源码直接跑（开发调试）

任一 GUI 都支持 `python <entry>.py` 起跑：

```bash
# 算法同步
python alg_sync/ui.py

# 算法发布
python alg_publish/alg_publish.py

# 算法重发布
python alg_republish/ui.py

# 不编辑版同步
python alg_sync_no_edit/ui.py

# 命令行同步（无 GUI）
python alg_sync/task.py
```

依赖：`httpx` + `PyQt6`，Python 3.11+。

### 2.5 停止 / 退出

GUI 直接关窗口；后台线程不会自动中断任务执行，等到本批结束才退出。

---

## 3. 功能介绍

### 3.1 alg_sync — 算法同步工具

**目的**：让本地 `resource/` 里的算法文件**重新进入平台**，且对原本已发布的算法保持发布状态不变（撤回再发）。

**GUI 怎么点**：

1. 启动 `算法同步工具v1.5.exe`，窗口标题：`算法同步工具 v1.5  |  designed by @yuzechao`
2. **连接配置** 区填 URL（默认 `http://10.16.11.1:31501`）、Username（默认 `admin`）、Password（必填，每次启动要填）
3. **更新配置** 区填"算法目录"（默认 `resource`，可以点 **浏览** 按钮改成任意目录）
4. 点红色 **开始更新** —— 后台线程登录平台 → 拉全部算法 → 扫描本地 → 匹配 `sourcePath` → 弹**确认对话框**显示命中列表和需取消发布列表
5. 确认无误点 **确定**，工具按 8 步流程逐个执行
6. 蓝色 **导出算法信息** 按钮：把当前缓存的平台算法完整字段写成 CSV（默认文件名 `{env_name}_alg_info_{YYYYMMDD}.csv`，UTF-8 BOM 编码，Excel 直接可读）

**8 步同步流程**（来自 `alg_sync/task.py`，GUI 版逻辑一致）：

1. 用 `AlgAPI` 登录平台 → 拿到 Bearer Token
2. `get_all_algorithms()` 自动翻页拉取平台全部算法，缓存到 `self.algorithms` 和 `self.source_map`
3. 扫描 `resource/` 下所有 `.zip` 和 `.py` 文件
4. 用本地文件名与平台 `sourcePath` 匹配（`common.api.match_local_files`）
5. 筛选出已发布（`isRelease == 1`）的算法
6. 对已发布算法**逐个取消发布**（保留下线，仅改状态）
7. **逐个**对所有命中算法：上传文件到 MinIO + 调 `edit_algorithm` 提交元信息
8. 对刚才取消发布的算法**逐个重新发布**（恢复原 `cores / resourceType / numReplicas`）

**产物 exe**：`算法同步工具v1.5.exe`

> 已发布算法最终回到原状态，但因为已经过「取消 → 上传 → 编辑 → 重发」，平台的运行实例是新建的，常用来把新版的 zip 推上线。

### 3.2 alg_publish — 算法发布工具

**目的**：用一张 CSV 表直接告诉平台每个算法是发布还是不发布、占多少核、多少副本、跑在 CPU 还是 GPU。

**GUI 怎么点**：

1. 启动 `算法发布工具v1.2.exe`，窗口标题：`算法发布工具 v1.2  |  designed by @yuzechao`
2. **CSV 配置** 区：启动时自动加载 exe 同级目录里文件名匹配 `publish_list_*.csv` 的**最近修改**的一份；也可以点 **浏览** 手动选别的
3. **连接配置** 区填 URL / Username / Password，**并发数**（默认 `3`）
4. 点绿色 **开始发布** —— 后台线程登录平台 → 拉全部算法 → 按 CSV 的 `算法名称`（大小写不敏感）匹配平台 `zhName` → 弹**确认对话框**，里面给出四类情况：
   - **已发现差异**：核数 / 副本数 / 发布位置 与 CSV 不一致
   - **已发布（无需操作）**：CSV 是、是、平台已发布
   - **待发布**：CSV 是、是、平台未发布
   - **CSV 设置不发布但平台已发布（建议取消发布）**：CSV 否、平台已发布
5. 点 **确定** → 按并发数分批发布（多线程并行，批间顺序；每批内并发请求同一批发布，完成后等所有线程结束再开下一批）
6. 发布完成后重新 `get_all_algorithms()` 校验每个算法的 `isRelease` 状态，输出最终结果：**全部成功** / 哪些失败

**CSV 格式**（列名必须**精确匹配**，编码优先 `utf-8-sig` → `utf-8` → `gbk` → `gb18030`）：

| 列名 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `算法名称` | 必填 | 字符串 | 匹配平台 `zhName`，大小写不敏感 |
| `是否发布` | 必填 | `是` / `否` | 决定要发布还是跳过 |
| `核数` | 可空 | 浮点 | 空 = 用平台已有值 |
| `副本数` | 可空 | 整数 | 空 = 用平台已有值 |
| `发布位置` | 可空 | `CPU` / `GPU` | 空 = 用平台已有值；`GPU` → `resourceType=2`，其它 → `1` |

**一个具体可用的 CSV 示例**（直接复制保存为 `publish_list.csv`）：

```csv
算法名称,是否发布,核数,副本数,发布位置
DeepAGI,否,0,0,GPU
deepSearch,是,1,1,CPU
view_data,是,1,1,CPU
pinch_point,是,1,1,CPU
restricted_new_build,是,1,1,CPU
restricted_judge,是,1,1,CPU
reconstruct_redesign,是,3,2,CPU
ex_fix_opt,是,1,1,CPU
ex_eval,是,1,1,CPU
info_check,是,1,1,CPU
```

**产物 exe**：`算法发布工具v1.2.exe`

> 工具只动「发布 / 不发布 / 核数 / 副本数 / 资源类型」5 个字段；CSV 里出现但**平台没有**的算法名会被列入"已发现差异"且**不会**自动创建算法（需在平台后台先建）。

### 3.3 alg_republish — 算法重发布工具

**目的**：让平台所有已发布算法**实例重建**（应用新配置 / 让 Pod 重新拉起）。流程固定为「取消发布 → 等待 1 秒 → 重新发布」。

**GUI 怎么点**：

1. 启动 `算法重发布工具v1.2.exe`，窗口标题：`算法重发布工具 v1.2  |  designed by @yuzechao`
2. **连接配置** 区填 URL / Username / Password
3. 点蓝色 **查看已发布算法** —— 后台线程登录平台 → 拉全部算法 → 过滤 `isRelease == 1` → 列出 `zhName / id / CPU|GPU / 核数 / 副本`，**执行发布流程** 按钮变可用
4. 点红色 **执行发布流程** —— 按列表顺序逐个算法处理：
   - 取消发布（`is_release=0`）
   - `time.sleep(1)`
   - 重新发布（`is_release=1`，用平台当前 `cores / resourceType / numReplicas`）
5. 「操作日志」区实时输出每步的 ✓ / ✗ 与错误信息

**产物 exe**：`算法重发布工具v1.2.exe`

> 中间那 1 秒的停顿是**硬编码**的不可改（来自 `alg_republish/ui.py` 的 `time.sleep(1)`）；它的作用是给平台侧完成下线清理留时间，省掉会让重新发布失败 / 状态错乱。

### 3.4 alg_sync_no_edit — 同步工具（不上传 edit）

**和 alg_sync 的区别**：

- **跳过** `edit_algorithm` 这一步（不重新提交算法元信息）
- 已发布算法 8 步缩减为「取消发布 → 上传文件 → 重新发布」
- 未发布算法只「上传文件」（因为原本就没发布过，自然也不需要 edit）

**什么时候用**：只想刷 zip 包但**不动平台元信息**（核数、副本数、发布位置等参数都保留）。alg_sync 在 edit 步骤里会把 `type = "{categoryOne}-{categoryTwo}"` 这种拼接重新写一次，对只改算法的场景是有副作用的。

**产物 exe**：`算法同步工具_不编辑v1.1.exe`

### 3.5 alg_manager — FastAPI 后端用的非 GUI 库

**目的**：把平台操作封装成纯 Python API，给 Web 后端复用。**没有 GUI 入口**。

**典型流程**：

```python
from alg_update.alg_manager import AlgManager

manager = AlgManager(base_url="http://10.16.11.1:31501",
                     username="admin", password="<your-password>")

manager.connect()                # 登录
manager.fetch_algorithms()       # 拉平台全部算法并缓存
manager.load_template("publish_list.csv")  # 加载 CSV
diff = manager.compare()         # 比对，产出 DiffResult
print(diff.summary())
# {'total': N, 'to_release_count': N, 'should_unrelease_count': N, ...}

# 发布待发布
result = manager.release_pending(concurrent=5)
print(f"成功 {result['success_count']}, 失败 {result['fail_count']}")

# 取消发布误发布
result = manager.unrelease_misreleased(concurrent=5)
```

**CSV 格式约定**：和 alg_publish GUI 一样（`算法名称, 是否发布, 核数, 副本数, 发布位置`）。

**命令行示例**：

```bash
python alg_manager.py publish_list.csv http://10.16.11.1:31501
```

不传 `base_url` 时默认 `http://10.16.11.45:31501`（这是历史默认值；要发给生产请显式带上目标 URL）。

---

## 4. 准备输入

### 4.1 alg_sync / alg_sync_no_edit —— `resource/` 目录

`alg_sync` 和 `alg_sync_no_edit` 都从「算法目录」（默认 `resource/`，与 exe 同级）里读：

- **支持的扩展名**：`.zip` 和 `.py`
- **文件名必须严格等于平台的 `sourcePath` 字段**（这决定了能否命中平台已有算法）
- 目录里所有 `.zip` / `.py` 都会被纳入匹配（**子目录不递归**，只扫顶层）

**一个示例 `resource/` 目录长这样**（与项目同仓真实示例一致）：

```
resource/
├── spc_pid_identification_analysis.py
├── spc_pid_identification_analysis_train.py
├── spc_process_data_PID.py
├── valve_anomaly_detection_infer.zip
└── valve_anomaly_detection_train.zip
```

匹配过程：

1. 工具扫描 `resource/`，拿到 5 个文件名
2. 拿每个文件名去 `platform_algorithms[i].sourcePath` 里查
3. 命中 → 进 `pending_found`，标注 `isExist=True`
4. 未命中 → 进 not-found 列表（**GUI 流程里这些不会被同步**，只列出给用户看）

> 想改算法目录？在 GUI 的"算法目录"输入框改成别的路径，或点 **浏览** 按钮选。

### 4.2 alg_publish —— publish_list_*.csv

详见 3.2 的 CSV 表格。重点再强调：

- **列名必须精确匹配**，中文：`算法名称 / 是否发布 / 核数 / 副本数 / 发布位置`
- 编码工具会按 `utf-8-sig` → `utf-8` → `gbk` → `gb18030` 顺序自动试，**一般直接用 UTF-8 就行**
- 推荐的文件名以 `publish_list_` 开头（例如 `publish_list_20260423.csv`），GUI 启动会自动选**最新修改**的一份
- `是否发布` 这一列传 `是`（中文）或 `否`；**严格区分**大小写、严格不能写成 `yes / no / true / false`

**完整可用示例**（直接复制保存）：

```csv
算法名称,是否发布,核数,副本数,发布位置
deepSearch,是,1,1,CPU
valve_anomaly_detection_train,是,2,1,GPU
view_data,否,0,0,CPU
```

### 4.3 alg_republish —— 无输入

不需要准备文件，只需要平台的连接信息。

---

## 5. HTTP 平台接口约定（平台方对接参考）

所有子工具都通过 `common/api.py`（alg_republish 用了同款本地副本 `alg_republish/api.py`）的 `AlgAPI` 类访问平台，路径前缀都是 `/alg-manager-web-v2.2-tpt`：

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/tpt-admin/system-manager/umsAdmin/login` | 登录，拿 Bearer Token |
| `POST` | `/alg-manager-web-v2.2-tpt/api/algorithm/page/1` | 分页列算法；`requestBase.page="N-M"` 控制分页 |
| `POST` | `/alg-manager-web-v2.2-tpt/api/algorithm/release` | 发布（`isRelease=1`） / 取消发布（`isRelease=0`），带 `cores / resourceType(1=CPU,2=GPU) / numReplicas` |
| `POST` | `/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio` | 上传 zip 到 MinIO（query: `built_in=1`） |
| `POST` | `/alg-manager-web-v2.2-tpt/api/algorithm/edit/1` | 提交算法信息（multipart/form-data，字段名 `algorithm`，值为 JSON 字符串；内部把 `type = "{categoryOne}-{categoryTwo}"`） |

**鉴权约定**：登录后从响应 `content.token` 取 Bearer Token，写到 `Authorization: Bearer <token>` 头里。HTTPS 模式额外会把 token 写到 cookie（`tpt-token`）和租户相关 cookie（`TptSaasUserTenantryId` / `tenant-id`）。

**业务码**：`code == "00000"` 视为成功；A0201 / A0202 / A0203 / A0230 是鉴权过期类，会被工具识别为"登录已过期，请重新登录"。

---

## 6. 完整调用示例

### 6.1 算法同步（GUI 版）

```cmd
:: 把算法 zip 拷到算法同步工具同级的 resource/ 下
:: 然后双击或在 cmd 里直接起
算法同步工具v1.5.exe
```

操作流程：填 URL → 填用户名密码 → 确认算法目录（默认 `resource`）→ 红色 **开始更新** → 弹框里看命中列表 → 点 **确定** → 控制台看每步结果。

### 6.2 算法同步（命令行版）

不开 GUI、用脚本调：

```bash
python alg_sync/task.py
```

默认 `base_url=http://10.16.11.1:31501`，硬编码凭据 `api_client / Supcon@1304`（在源码里改 `run_task()` 调参）。终端打印 8 步过程 + 最终汇总。

### 6.3 批量发布（CSV 驱动）

```cmd
:: 把 publish_list_20260423.csv 放到发布工具同目录
:: 启动后工具自动选最新那份 CSV
算法发布工具v1.2.exe

:: 或者 CLI 直接跑源码
python alg_publish/alg_publish.py
```

操作流程：自动加载最新 CSV → 填连接信息 → 调并发数（默认 3）→ 绿色 **开始发布** → 弹框看差异 / 待发布 / 误发布 → 点 **确定** → 等待批发布 + 最终校验。

### 6.4 重发布

```cmd
算法重发布工具v1.2.exe
```

操作流程：填连接信息 → 蓝色 **查看已发布算法** → 红色 **执行发布流程** → 看日志。

### 6.5 后端集成（FastAPI）

```python
from alg_update.alg_manager import AlgManager

def sync_algorithms(csv_path: str, base_url: str, username: str, password: str):
    manager = AlgManager(base_url=base_url, username=username, password=password)
    manager.connect()
    manager.fetch_algorithms()
    manager.load_template(csv_path)
    diff = manager.compare()
    summary = diff.summary()
    release_result = manager.release_pending(concurrent=5)
    return {
        "summary": summary,
        "release": release_result,
    }
```

CSV 格式同 3.2 / 4.2。

### 6.6 不编辑版同步（只刷包）

```cmd
算法同步工具_不编辑v1.1.exe
```

操作流程同 6.1，只是不会调 `edit_algorithm` 那一步。

---

## 7. 已知坑 & 注意事项

> **URL/凭据在多处重复维护**：四个 GUI 默认值都在各自的 `ui.py`（URL=`http://10.16.11.1:31501`，Username=`admin`），`api.py` / `common/api.py` / `alg_republish/api.py` 各有一份（且 `common/api.py` 多支持 HTTPS cookie / tenant 分支），`alg_manager.py` 默认 `http://10.16.11.45:31501` 且 `username=api_client, password=Supcon@1304`。**改生产 URL 时记得这 5 个文件都过一遍**，别只改 GUI 那一份。

> **README 写 v1.3，实际是 v1.5**：仓库 README.md / memory.md 还写着 `alg_sync v1.3 / alg_publish v1.0`，但 spec 名和打包产物已经到 v1.5 / v1.2。**以窗口标题和 exe 文件名为准**。

> **`alg_publish/algdevp3.py` 是旧版本**：用 `requests` 写、硬编码 `10.16.11.45 / admin / 123456`、`BATCH_SIZE=3` 的命令行脚本，**新需求请用 `alg_publish.py`**，不要修改它。

> **`alg_update/data-hub-tool/` 是过时快照**（本仓库其它目录有同名项目 `data-hub-tool/`，是另起一摊的），应该删；当前在 `alg_update/` 下不应再出现。

> **`api.py` 和 `common/api.py` 内容已分叉**：顶层 `api.py` 是老版本（无 HTTPS / tenant 支持），`common/api.py` 是新版。GUI 工具全部用新版；`alg_sync/task.py` 顶层 CLI 还是 `from api import AlgAPI`，可能踩到老版本——**生产用建议直接 import `common.api`**。

> **`alg_manager.py` 走的是 `http://10.16.11.45:31501` 和 `api_client / Supcon@1304`**（dataclass 注释里也提到 `http://10.16.11.1:31501`），**实跑生产请在调用处显式传 `base_url/username/password`，不要依赖默认值**。

> **生产用窗口不要用「导出算法信息」** 把含 token 的信息带出内网——它的 CSV 含平台完整算法字段，但不带 token，OK；但跨网导出前先确认字段合规。

---

## 8. 另见

`alg_update/alg_toolbox/` 是这套工具的 **Go / Wails** 重写版（`alg_toolbox.exe` 已打包产出 ~6.5MB），用 `app.go / algapi.go / publish.go / sync.go` 等模块组织。当前**仍在迁移中**，功能成熟度另行确认；如要尝试可直接双击 `alg_toolbox/alg_toolbox.exe`、或进 `alg_toolbox/` 跑 `wails dev` / `wails build`。

---

designed by @yuzechao
