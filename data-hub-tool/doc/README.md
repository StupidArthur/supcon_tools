# hisdata-migrate 工具文档

> **项目**：`data-hub-tool` 目录下的位号数据迁移工具
> **状态**：v0.91（2026-07-03）
> **作者**：designed by @yuzechao

## 这是什么

**hisdata-migrate** 是数据中枢平台（`ibd-data-hub-web-v2.2`）的**位号历史值迁移工具**。

核心场景：从一个环境导出位号的历史数据，在另一个环境重建位号并把数据导入回去。

## 文档目录

| 文档 | 内容 |
|---|---|
| [requirements.md](requirements.md) | **需求**：为什么做、用户场景、功能边界 |
| [design.md](design.md) | **设计**：架构、模块、UI 抽象、7 阶段流水线 |
| [data-formats.md](data-formats.md) | **数据格式**：平台导出 / 导入 xlsx 详细规范 |
| [notes.md](notes.md) | **备注**：踩过的坑、已知问题、注意事项 |

## 快速上手

### 命令行（CLI）

```bash
# 安装依赖
pip install -r requirements.txt
# 或手动: pip install PyQt6 openpyxl httpx 'numpy<2.0'

# 迁移：源 xlsx → 目标环境
python migrate.py --xlsx export.xlsx \
                  --target-url http://10.10.58.179:31501 \
                  --target-user admin \
                  --target-password 123456
```

### GUI（PyQt6）

```bash
python migrate_gui.py
```

弹窗式（v0.91）：
- 选源 xlsx → 填目标 URL / 用户 / 密码 → 点"开始迁移"
- 6 阶段自动跑：读源数据 → 连接目标 → 检查 tag → 最终计划 → 执行迁移 → 验证
- 单一 OUTPUT textarea：阶段日志、表格、warn/error 都在这滚动查看（替代过去的 QStackedWidget 多页 + 折叠日志）
- 步骤条 6 个 pill 实时变色：pending(灰) → active(蓝) → done(绿)
- 默认窗口 1180 × 900，避免输入框被压
- 出错（仅两类）弹 modal：`QMessageBox.warning("位号缺失", ...)` 或 `QMessageBox.critical("失败", ...)`
- 生产日志：`<exe 同级>/logs/YYYY-MM-DD.log`，毫秒级，控制台 + 文件双端输出

### 打包 EXE

```bash
# 1. 先装锁定版本的依赖 (numpy 必须 <2.0, 否则老机器跑不起来 X86_V2 指令集)
pip install -r requirements.txt

# 2. 用 spec 打包 (已固化参数 + UPX 压缩)
pyinstaller hisdata-migrate-v0.91.spec --clean

# 产物: dist/hisdata-migrate-v0.91.exe
```

输出 `dist/hisdata-migrate-v0.9.exe`（约 57 MB），可拷到无 Python 的 Windows 直接跑。

## 文件清单

### 核心工具

| 文件 | 用途 |
|---|---|
| `migrate.py` | 迁移业务逻辑 + UI 抽象 + CliUI + 6 阶段流水线 |
| `migrate_gui.py` | PyQt6 GUI（单 OUTPUT textarea, 步骤条颜色实时变化） |
| `log_config.py` | 生产日志：exe 同级 `logs/YYYY-MM-DD.log` + 控制台，毫秒级 |
| `xlsx_io.py` | xlsx 读 / 写抽象层 |
| `convert.py` | 平台导出格式 (long) → 导入格式 (wide)，时间列取 App Time（缺失回退 Tag Time），兼容 datetime + 亚秒 |
| `common_api.py` | AlgAPI：登录 + 位号 CRUD + 3 个历史值导入 + 1 个查询 API，默认 httpx timeout = 60s |
| `requirements.txt` | 锁定依赖：`PyQt6 / openpyxl / httpx / numpy<2.0 / pyinstaller` |

### 辅助脚本（`scripts/`）

| 文件 | 用途 |
|---|---|
| `convert_export_to_import.py` | CLI：导出 xlsx → 导入 xlsx，可选 `--upload` 直接上传 |
| `gen_t_double_test.py` | 生成 long 格式测试 xlsx（可参数化） |
| `_path_helper.py` | sys.path 引导，供 scripts/ 导入根目录模块 |

### 接口文档

| 文件 | 用途 |
|---|---|
| `tag-value-import-api.md` | 平台 `TagValueController` 导入 API 调用说明（含 3 个导入端点 + CSV） |

### 测试数据

| 文件 | tag | 点数 | 时间 |
|---|---|---|---|
| `history_all_type.xlsx` | aa_* (11) | 10000 | 2026-06-23 ~ 06-24 |
| `new_output.xlsx` | aa_* (11) | 10000 | 2026-06-23 ~ 06-24（平台导出快照）|
| `new_output_bb.xlsx` | bb_* (11) | 10000 | 同上（aa_ 改名 bb_）|
| `new_output_bb_shifted.xlsx` | bb_* (11) | 10000 | 2026-09-01 ~ 09-02（+70天）|
| `t_double_test_export.xlsx` | t_double_13..20 (8) | 10000 | 2026-10-15 ~ 10-16 |
| `t_double_21_30_export.xlsx` | t_double_21..30 (10) | 1000 | 2026-11-01 |

## 平台信息

- **平台**：ibd-data-hub-web-v2.2
- **基础 URL**：`http://10.10.58.179:31501`（开发环境）
- **认证**：admin / 123456
- **架构**：x86-64 Windows / Linux
- **租户**：单租户，HTTP 模式（不需要 tenantId）

## 关键概念

| 术语 | 含义 |
|---|---|
| **位号 (tag)** | 平台中的数据点，如 `aa_float` |
| **dataType** | 1=BOOLEAN, 2=S_BYTE, 3=BYTE, 4=SHORT, 5=U_SHORT, 6=INT, 7=U_INT, 8=LONG, 9=U_LONG, 10=FLOAT, 11=DOUBLE |
| **long 格式** | 平台导出格式：每 tag 1 sheet, 4 列, 倒序 |
| **wide 格式** | 平台导入格式：1 sheet, A1 元信息, B+ tag 值, 正序 |
| **数据点** | (时间, 值) 一对，1 个 tag 在 1 个时刻的数值 |

## 版本

- **v0.91**（当前，2026-07-05）：
  - GUI 重构：单一 OUTPUT textarea，无 QStackedWidget 多页、无折叠日志、无蓝色进度条；默认窗口 1180×900
  - 步骤条 bug 修复：set_state 改用直接属性，active=蓝底白字、done=浅绿底绿字，阶段推进时颜色变化明显
  - 6 阶段流水线，无决策环节，has_data 默认 overwrite，无完成通知弹窗
  - 缺位号走专用弹窗（列出全部缺失位号）
  - convert 取 App Time（兼容老格式 + 新格式，避免塌缩）
  - 时间列解析兼容 datetime + 亚秒
  - verify / has_data 查询窗口：用实际数据窗口代替 1970-2099 默认值，避免 timeout
  - httpx 默认 timeout 30s → 60s
  - 生产日志：exe 同级 `logs/YYYY-MM-DD.log`，毫秒级双端输出
  - numpy 锁版 <2.0（X86_V2 指令集兼容）
- 历史：
  - **v0.9**（2026-06-29）：7 阶段流水线，CLI/GUI 都有 DecisionDialog，HAS_DATA_OPTIONS 默认 abort
  - **v0.x**：命令行导入脚本（import_history.py）
  - **早期**：API 探针（test_api.py）
