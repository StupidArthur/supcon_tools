# hisdata-migrate 用户手册

> 把数据中枢平台（`ibd-data-hub-web-v2.2`）在 A 环境导出的位号历史值 xlsx，转格式后在 B 环境重建并导入。
>
> **当前版本**：v0.91
>
> designed by @yuzechao

---

## 1. 这是什么

**hisdata-migrate** 是数据中枢平台 `ibd-data-hub-web-v2.2` 的位号历史值迁移工具。核心场景：把一个环境的位号历史数据导出 xlsx，转成平台能直接导入的宽表 xlsx，通过 HTTP 上传并在目标环境验证落地。

工具提供两种形态：

- **GUI**（PyQt6）：选源 xlsx → 填目标 URL / 用户 / 密码 → 点"开始迁移"，6 阶段自动跑。
- **CLI**（`python migrate.py`）：一行命令走完整流程，适合脚本化和批处理。

平台版本：ibd-data-hub-web-v2.2。认证：admin / 123456（开发环境示例）。架构：x86-64 Windows / Linux，单租户，HTTP 模式不需要 tenantId。

---

## 2. 使用入门

### 2.1 安装依赖

源码运行需要 Python 3.10+：

```bash
pip install -r requirements.txt
# 或手动：pip install PyQt6 openpyxl httpx 'numpy<2.0'
```

> numpy 必须 `<2.0`：numpy 2.x 用了 X86_V2 baseline 指令集，老机器跑不起来（2026-07 用户反馈）。依赖已锁版本。

### 2.2 GUI 启动

```bash
python migrate_gui.py
```

默认窗口 1180 × 900。操作：

1. 点"浏览…"选源 xlsx（平台导出的长表 xlsx）
2. 填目标 URL（例：`http://10.10.58.179:31501`）、用户名、密码
3. 点"开始迁移"

6 阶段横向 stepper 实时变色（pending 灰 → active 蓝 → done 浅绿），所有日志、阶段、表格都进 OUTPUT 区滚动查看。状态行在底部，显示"迁移中… / 完成 / 失败"。点"取消"可中断。

GUI 会用 `QSettings` 记忆上次 URL / 用户 / xlsx（密码不存）。默认 URL 填的是开发环境 `http://10.10.58.179:31501`。

> 打包版直接双击 `hisdata-migrate-v0.91.exe`，无需 Python 环境。

### 2.3 CLI 启动

```
python migrate.py --xlsx <源xlsx> --target-url <URL> --target-user <user> --target-password <pwd> [--verify-wait <sec>]
```

参数说明：

| 参数 | 必填 | 默认 | 含义 |
|---|---|---|---|
| `--xlsx` | 是 | — | 源数据 xlsx 路径（平台导出格式，长表） |
| `--target-url` | 是 | — | 目标环境 URL，例 `http://target-env:31501` |
| `--target-user` | 是 | — | 目标环境登录用户名 |
| `--target-password` | 是 | — | 目标环境登录密码 |
| `--verify-wait` | 否 | `15` | 验证前等异步处理的秒数 |

退出码：

- `0` — 正常完成
- `1` — 用户取消 / 缺位号中止
- `2` — xlsx 文件不存在
- `3` — 未捕获异常

### 2.4 一个具体的案例

A 环境导出 `export.xlsx`（11 个 tag，每个 10000 点），目标环境 URL `http://10.10.58.179:31501`，admin / 123456：

```cmd
python migrate.py --xlsx export.xlsx ^
                  --target-url http://10.10.58.179:31501 ^
                  --target-user admin ^
                  --target-password 123456
```

执行后控制台按阶段输出，跑完会打印"完成: 导入 11 个 tag, 跳过 0 个"。

---

## 3. 功能介绍

### 3.1 总述 — 迁移的 6 阶段流水线

工具把"读源 → 连目标 → 查 tag → 列计划 → 上传 → 验证"串成 6 阶段流水线，UI 实时反映进度：

| 阶段 | 标题 | 做什么 |
|---|---|---|
| 1 | 读源数据 | 读源 xlsx，统计每个 tag（sheet）的数据点数 |
| 2 | 连接目标环境 | 登录目标环境，拿 Bearer token |
| 3 | 检查 tag | 拉目标环境全部 tag 建索引，逐个查 has_data |
| 4 | 最终计划 | 缺位号则中止并弹列表；已有数据默认 overwrite |
| 5 | 执行迁移 | long → wide 格式转换，写中间 xlsx，HTTP 上传 |
| 6 | 验证 | 等异步处理后，用实际数据窗口查回数据点数 |

### 3.2 v0.91 关键变更（与 v0.9 的区别）

- 移除决策阶段：has_data 的 tag 默认全部 overwrite，不弹窗问
- GUI 重构：单一 OUTPUT textarea（替代过去的 QStackedWidget 多页 + 折叠日志）
- 默认窗口 1180 × 900
- convert 取 App Time（兼容老格式 + 新格式，避免时间塌缩）
- 时间列解析兼容 datetime + 亚秒（`yyyy-MM-dd HH:mm:ss.%f`）
- 验证窗口：用实际导入窗口代替 1970-2099 默认值（29 tags 时宽范围会 timeout，2026-07 用户反馈）
- httpx 默认 timeout 30s → 60s
- numpy 锁版 < 2.0（X86_V2 指令集兼容）
- 无完成通知弹窗

### 3.3 支持的操作系统

- **Windows** 10 / 11（64 位）——打包 exe 直接跑
- **Linux**：CentOS、Ubuntu 等 —— 跑 Python 源码

打包产物 `hisdata-migrate-v0.91.exe`（约 57 MB）是单文件，目标机不需要装 Python。

### 3.4 关键概念

| 术语 | 含义 |
|---|---|
| **位号 (tag)** | 平台中的数据点，如 `aa_float` |
| **long 格式** | 平台导出格式：每 tag 1 sheet，4 列，倒序 |
| **wide 格式** | 平台导入格式：1 sheet，A1 元信息，B+ tag 值 |
| **dataType** | 1=BOOLEAN, 2=S_BYTE, 3=BYTE, 4=SHORT, 5=U_SHORT, 6=INT, 7=U_INT, 8=LONG, 9=U_LONG, 10=FLOAT, 11=DOUBLE |
| **数据点** | (时间, 值) 一对，1 个 tag 在 1 个时刻的数值 |

### 3.5 缺位号的处理（v0.91）

目标环境缺源 xlsx 中某些 tag 时，工具会：

1. 收集**全部**缺失位号（不是只报第一个）
2. GUI 弹专用模态框"位号缺失"，列出全部：
   ```
   目标环境缺少以下位号，无法继续迁移：

     • aa_float_001
     • aa_int_005
     • aa_bool_010

   请先在平台 UI 手动创建这些位号（注意 dataType 匹配），然后重跑迁移。
   ```
3. CLI 退出码 1，stderr 列出缺失位号

> 创建缺失位号后重跑即可，工具不会覆盖已正确存在的位号。

### 3.6 验证策略

工具在阶段 6 验证导入是否真落地：

- 等异步处理 `verify-wait` 秒（默认 15s）
- 用**实际数据窗口**（从源 xlsx 提取）查 `getHistoryValueFromDB`，不是 1970-2099 宽范围
- 逐 tag 验证 total > 0 才算通过

```
✅ 验证通过 (10/11 个 tag 有数据)
```

> 实测 29 个 tag + 1970-2099 宽范围会触发 timeout（2026-07 用户反馈）。v0.91 用实际数据窗口规避。

### 3.7 取消操作

GUI 和 CLI 都支持协作式取消（`threading.Event`）：

- **GUI**：点"取消"按钮，工具在阶段间检查取消标记，安全中断
- **CLI**：`Ctrl + C`，触发 `MigrationCancelled`，退出码 1

阶段间的取消点是：读 xlsx 后、登录后、检查 tag 后、上传前、验证循环（每 0.5s 检查）。

### 3.8 日志位置和格式

`log_config.py` 把日志写到：

- **打包版**：`exe 同级目录/logs/YYYY-MM-DD.log`
- **源码版**：项目根 `/logs/YYYY-MM-DD.log`
- 控制台：与文件用同一格式

格式（毫秒级）：

```
2026-07-06 14:32:15.428 [INFO ] [migrate] 迁移开始 xlsx=export.xlsx url=http://... user=admin
2026-07-06 14:32:15.612 [INFO ] [common_api] 登录成功: token 长度=180
2026-07-06 14:32:18.733 [INFO ] [migrate] [stage 5] 上传响应: status=200 code=00000 msg=None requestId=...
```

出问题把整个 `logs/` 文件夹打包回来。

---

## 4. 准备输入：xlsx 文件

### 4.1 格式总览（long 格式，平台导出格式）

源 xlsx 是平台 A 环境的导出文件，特征：

- **每个 tag 1 个 sheet**，sheet 名 = tag 名
- 每个 sheet **4 列固定**：`Tag Time, App Time, Quality, Tag Value`
- 第 1 行表头，第 2 行起数据
- 时间格式 `yyyy-MM-dd HH:mm:ss`（横杠，空格分隔，**导出格式**）
- 可选带亚秒精度：`yyyy-MM-dd HH:mm:ss.%f`（5~6 位小数，v0.91 兼容）
- **倒序**：最新数据在最上面
- Tag Value 是字符串（DOUBLE/FLOAT 带 `.0`，INT 类无小数，BOOLEAN 0/1）
- Quality 固定 192（不写入新表）
- **编码**：UTF-8（GBK 也兼容，自动识别）

### 4.2 时间列的选择（v0.91 关键变更）

工具在 long → wide 转换时优先取 **App Time**（第 2 列），缺失时回退到 Tag Time（第 1 列）：

| 格式 | Tag Time（第 1 列） | App Time（第 2 列） | 工具取哪一列 |
|---|---|---|---|
| 老格式 | 采样时间 | 采样时间 | 任一 |
| 新格式 | 值设置时间 | 真实采样时间 | App Time |

> 这是为了避免新格式下用 Tag Time 导致时间塌缩（同一值所有行的 Tag Time 一致）。

### 4.3 4 列的具体含义

| 列 | 表头 | 含义 | 工具处理 |
|---|---|---|---|
| 1 | Tag Time | 值设置时间 | App Time 缺失时回退 |
| 2 | App Time | 真实采样时间 | **优先**用作采样时间 |
| 3 | Quality | 数据质量码 | **丢弃**，不写入新表 |
| 4 | Tag Value | 位号值（字符串） | 写入 wide 表 |

### 4.4 一个完整可用的示例（直接复制生成）

每个 sheet 形如：

```
Tag Time                | App Time                | Quality | Tag Value
2026-06-23 23:59:30.029 | 2026-06-23 23:59:30.029 | 192     | 42.0
2026-06-23 23:59:20.018 | 2026-06-23 23:59:20.018 | 192     | 41.0
2026-06-23 23:59:10.012 | 2026-06-23 23:59:10.012 | 192     | 40.0
... (倒序)
2026-06-23 00:00:00.000 | 2026-06-23 00:00:00.000 | 192     | 0.0
```

`sheet 名 = tag 名 = aa_float` 这种形式。其它 sheet 同结构，tag 名不同（`aa_int`、`aa_bool` 等）。

### 4.5 转换后的输出（wide 格式，平台导入格式）

工具在阶段 5 自动把源 xlsx 转成宽表，输出到 `<源xlsx>_for_import.xlsx`：

```
A1: 2026/06/23 00:00:00,2026/06/23 23:59:30,10,0/5 * * * * ?
A2: (空)
B1:  aa_float
C1:  aa_int
D1:  aa_bool
A3:  2026/06/23 23:59:30 | 42.0 | 1 | 0
A4:  2026/06/23 23:59:20 | 41.0 | 0 | 1
... (保持原方向)
```

要点：

- **A1** = `startTime,endTime,frequency,cron`（4 段逗号分隔）
- **时间格式**：`yyyy/MM/dd HH:mm:ss`（斜杠，**导入格式**，与导出格式不同）
- **A2 留空**
- **B1+** = tag 名
- **A3+** = 数据行，列顺序 = `时间, tag1 值, tag2 值, ...`

> 时间格式的导出/导入差异（横杠 vs 斜杠）是平台规范要求，工具自动处理。

### 4.6 已废弃的 CSV 路径

平台早期支持 `importCSVTagValueHistory`（CSV 导入端点），现已废弃。当前工具走 `importTagValueHistory`（Excel/ZIP 导入端点），**不要再提供 CSV 文件**。

---

## 5. 已知坑 & 注意事项

### 5.1 依赖坑

| 坑 | 现象 | 解决 |
|---|---|---|
| numpy 2.x | 老机器启动报 GLIBC / 指令集错误 | 必须装 `numpy<2.0` |
| httpx timeout | 29 tags 宽范围 `getHistoryValueFromDB` 超时 | v0.91 已用实际数据窗口规避；如仍超时，调大 `--verify-wait` 无效，需调工具源码 |
| QSettings | 跨机器/跨用户配置会串 | 只在同一台机器的同一用户下使用 |

### 5.2 数据坑

| 坑 | 现象 | 解决 |
|---|---|---|
| 时间格式错误 | 转换阶段报错"无法解析时间字符串" | 导出格式必须是 `yyyy-MM-dd HH:mm:ss`，可选带 `.%f` |
| 缺位号 | 阶段 3/4 中止，弹"位号缺失"列表 | 在目标平台 UI 手动创建，注意 dataType 匹配 |
| dataType 不匹配 | 导入成功但查询无数据 | 创建位号时确认 dataType 与源 xlsx 一致（1=BOOLEAN, ..., 11=DOUBLE） |
| tag 在回收站 | 目标环境的 `list_tags` 查不到，但实际存在 | `batchDeleteLogic` 是软删，位号进回收站不进列表；先用 `tag_cleaner.py diagnose` 看分布 |
| 时间窗口跨度过大 | 验证阶段 timeout | v0.91 已自动用源数据窗口；如仍超时需拆分导入 |

### 5.3 平台坑

| 坑 | 说明 |
|---|---|
| 异步处理 | `importTagValueHistory` 返回 200 仅代表请求接受，**实际写入异步**，必须用阶段 6 验证 |
| 宽范围查询 | 平台 `getHistoryValueFromDB` 在 tag 多 + 时间窗口大时 timeout，v0.91 已规避 |
| tagType 分布 | 平台 `list_tags` 默认只返回 `tagType=1` 的位号，本工具在阶段 3 已遍历 `1/4/0/2/3/5` 全量拉取 |
| 双环境时区 | 平台按本地时区存时间，跨时区迁移可能偏移，导出/导入前确认时区 |

### 5.4 操作建议

- 迁移前先在 GUI 里看 OUTPUT 区的"源 xlsx 位号与点数"表，确认 tag 名和点数符合预期
- 已存在位号默认 overwrite；如果想保留旧数据，先在平台手动备份
- 大文件迁移（> 10 万点）建议拆份，避免单次异步处理超时
- 失败时把 `logs/` 整个文件夹打包回来

---

## 6. 进阶用法

### 6.1 用辅助脚本单独转换（不上传）

如果只想转格式、不上传：

```bash
python scripts/convert_export_to_import.py --input export.xlsx --output history_for_import.xlsx
```

加 `--upload` 会自动登录默认环境（`http://10.10.58.179:31501`）并上传。

### 6.2 大量生成测试数据

```bash
python scripts/gen_export_datasets.py
# 默认：50 份 × 22 个 tag × 1000 点，写到 data/inputs/datasets/
```

可选参数：

- `--points N` — 每位号数据点数（默认 1000）
- `--per-type N` — 每份每种类型几个位号（默认 2）
- `--freq N` — 采样周期秒（默认 10）
- `--out-dir DIR` — 输出目录
- `--prefix STR` — 位号名前缀（默认 `omc`）

### 6.3 生成位号注册 xlsx

在平台"位号管理"页批量建位号：

```bash
python scripts/gen_tag_register.py --prefix omc --count 100 --ds OMC117 --out tag_register.xlsx
```

### 6.4 位号清理工具（软删 / 物理清 / 诊断）

```bash
python scripts/tag_cleaner.py diagnose                       # 诊断：列 tagType 分布
python scripts/tag_cleaner.py soft --yes --batch-size 1000   # 软删（进回收站，可恢复）
python scripts/tag_cleaner.py hard --yes --batch-size 1000   # 物理清（不可恢复）
python scripts/tag_cleaner.py all --yes --batch-size 1000    # 一条龙彻底清空
```

连接参数可通过环境变量覆盖：

```bash
set DATA_HUB_URL=http://other-env:31501
set DATA_HUB_USER=admin
set DATA_HUB_PASSWORD=xxx
python scripts/tag_cleaner.py diagnose
```

> 默认是 dry-run，加 `--yes` 才真删。`--batch-size` 不传 = 单次全删；传了 = 分批探上限。

---

## 7. 打包

源码 → 单文件 exe：

```bash
# 1. 装锁定依赖
pip install -r requirements.txt

# 2. 用 spec 打包（已固化参数 + UPX 压缩）
pyinstaller hisdata-migrate-v0.91.spec --clean

# 产物：dist/hisdata-migrate-v0.91.exe (~ 57 MB)
```

打包后 logs/ 在 exe 同级目录，可拷到无 Python 的 Windows 直接跑。

---

## 8. 完整可用的调用示例

### 8.1 CLI：开发环境

```cmd
python migrate.py --xlsx data\inputs\export.xlsx ^
                  --target-url http://10.10.58.179:31501 ^
                  --target-user admin ^
                  --target-password 123456
```

### 8.2 CLI：生产环境 + 调大验证等待

```cmd
python migrate.py --xlsx D:\migration\export_all_11types.xlsx ^
                  --target-url http://prod-env:31501 ^
                  --target-user admin ^
                  --target-password xxx ^
                  --verify-wait 30
```

### 8.3 打包版

```cmd
hisdata-migrate-v0.91.exe --xlsx export.xlsx ^
                          --target-url http://target:31501 ^
                          --target-user admin ^
                          --target-password yyy
```

### 8.4 GUI 流程

1. 双击 `hisdata-migrate-v0.91.exe`（或 `python migrate_gui.py`）
2. 点"浏览…"选 `export.xlsx`
3. 填 `http://target-env:31501` / `admin` / 密码
4. 点"开始迁移"
5. 看 OUTPUT 区滚动日志，6 个 pill 依次变蓝变绿
6. 完成后状态行显示"完成: 导入 N 个，跳过 M 个"

---

designed by @yuzechao