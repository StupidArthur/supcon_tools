# 数据文件格式

平台有两套数据 xlsx 格式：**导出格式**（long）和**导入格式**（wide）。两者**结构不同**，不能直接互用。

## 1. 平台导出格式（long）

平台 UI 的"导出"功能产出的 xlsx。

### 1.1 文件结构

```
xlsx 文件
├── Sheet "aa_float"        ← 1 个 tag = 1 个 sheet
│   ├── 第 1 行: 表头
│   └── 第 2 行起: 数据
├── Sheet "aa_long"
│   ...
└── Sheet "aa_double"
    ...
```

### 1.2 每个 sheet 的结构

| 列 | 名称 | 类型 | 例子 |
|---|---|---|---|
| 1 | Tag Time | 字符串 (yyyy-MM-dd HH:mm:ss) | `2026-06-24 03:46:30` |
| 2 | App Time | 字符串 (yyyy-MM-dd HH:mm:ss) | `2026-06-24 03:46:30` |
| 3 | Quality | 数字 | `192` |
| 4 | Tag Value | **字符串** | `'99.0'` / `'99'` / `'1'` / `'0'` |

### 1.3 关键特征

- **每个 tag 单独一个 sheet**（sheet 名 = tag 名）
- **时间方向：倒序**（最新在前）
- **时间格式：横杠** `yyyy-MM-dd HH:mm:ss`（带空格分隔）
- **Quality 固定 192**（良好质量）
- **Tag Value 总是字符串**（即使是数值，平台也存为字符串）
  - DOUBLE/FLOAT: `'99.0'`（带 `.0`）
  - INT 类（U_INT/INT/SHORT/BYTE 等）: `'99'`（无小数）
  - BOOLEAN: `'0'` / `'1'`

### 1.4 完整例子

```
Sheet: aa_float
+-----------+-----------+---------+-----------+
| Tag Time  | App Time  | Quality | Tag Value |
+-----------+-----------+---------+-----------+
| 2026-06-24 03:46:30 | 2026-06-24 03:46:30 | 192 | 99.0 |
| 2026-06-24 03:46:20 | 2026-06-24 03:46:20 | 192 | 98.0 |
| 2026-06-24 03:46:10 | 2026-06-24 03:46:10 | 192 | 97.0 |
| ...       | ...       | ...     | ...       |
| 2026-06-23 00:00:00 | 2026-06-23 00:00:00 | 192 | 0.0  |
+-----------+-----------+---------+-----------+
```

## 2. 平台导入格式（wide）

`importTagValueHistory` / `convert_export_to_import` 产出的 xlsx。

### 2.1 文件结构

```
xlsx 文件
└── Sheet "history"           ← 只有 1 个 sheet
    ├── 第 1 行: A1 元信息 + B1+ 位号名
    ├── 第 2 行: 跳过
    └── 第 3 行起: 数据
```

### 2.2 详细布局

| 位置 | 内容 | 例子 |
|---|---|---|
| **A1** | 元信息 4 段（逗号分隔） | `2026/06/23 00:00:00,2026/06/24 03:46:30,10,0/5 * * * * ?` |
| A2 | （留空，平台忽略） | |
| **B1** | 第 1 个 tag 名 | `aa_float` |
| C1 | 第 2 个 tag 名 | `aa_double` |
| ... | ... | |
| A3 | 第 1 个时间点 | `2026/06/23 00:00:00` |
| B3 | 第 1 个时间点, aa_float 的值 | `0` 或 `'0.0'` |
| C3 | 第 1 个时间点, aa_double 的值 | `0` |
| A4 | 第 2 个时间点 | `2026/06/23 00:00:10` |
| ... | ... | |

### 2.3 A1 元信息 4 段

| 段 | 名称 | 例子 | 必需？ |
|---|---|---|---|
| 1 | startTime | `2026/06/23 00:00:00` | 否（API 可覆盖） |
| 2 | endTime | `2026/06/24 03:46:30` | 否 |
| 3 | frequency（秒）| `10` | 否 |
| 4 | cron | `0/5 * * * * ?` | 否（**但必须用活的**）|

### 2.4 关键约束

| 项 | 要求 | 不行的话 |
|---|---|---|
| 时间格式 | `yyyy/MM/dd HH:mm:ss`（**斜杠**）| `yyyy-MM-dd` 静默失败 |
| cron | 活的（如 `0/5 * * * * ?`）| 占位（`0 0 0 1 1 ?`）不触发 |
| 列数 | 1+ 个 tag 列 | 空列（没 B+ 列）失败 |
| 行数 | 至少 1 行数据 | 空数据失败 |
| 时间方向 | 任意 | 都行（V3 验证过） |
| 值类型 | 数字或字符串 | 都行（V2 验证过强转） |
| 值域 | 在 dataType 范围内 | 越界失败 / 静默丢弃 |

### 2.5 完整例子

```
Sheet: history
A1: 2026/06/23 00:00:00,2026/06/24 03:46:30,10,0/5 * * * * ?
B1: aa_float | C1: aa_double | D1: aa_long | ...
A2: (空)
A3: 2026/06/23 00:00:00 | B3: 0 | C3: 0 | D3: 0 | ...
A4: 2026/06/23 00:00:10 | B4: 1 | C4: 1 | D4: 1 | ...
A5: 2026/06/23 00:00:20 | B5: 2 | C5: 2 | D5: 2 | ...
...
```

## 3. 转换对照表

| 项 | 导出 (long) | 导入 (wide) | 转换方式 |
|---|---|---|---|
| 文件结构 | 多 sheet，每 tag 1 个 | 1 sheet, tags 作列 | **长转宽 pivot** |
| sheet 名 / 列头 | sheet 名 = tag 名 | B1, C1, ... | 收集所有 tag 名 |
| 时间格式 | `yyyy-MM-dd HH:mm:ss` | `yyyy/MM/dd HH:mm:ss` | **横杠 - 改 斜杠 /** |
| A1 | 无 | 4 段元信息 | 从数据归纳 (startTime/endTime/freq) + 活 cron |
| Tag Value 类型 | 字符串 (`'99.0'`) | 数字 (`99`) 或字符串 | **不转换**（V2 验证过平台强转）|
| 时间方向 | 倒序（新→旧）| 正序（旧→新）| **不转换**（V3 验证过倒序能落地）|
| Quality 列 | 有 | 无 | **丢弃** |
| App Time 列 | 有 | 无 | **丢弃** |

## 4. 转换工具

`convert.py` 提供标准化函数：

```python
from convert import convert_export_to_wide_input

sheets = read_all_sheets("export.xlsx")  # dict[tag, rows]
wide = convert_export_to_wide_input(sheets)
# wide = {
#   "a1": "...,...,...,0/5 * * * * ?",
#   "headers": ["aa_float", "aa_double", ...],
#   "rows": [["2026/06/23 00:00:00", 0, 0, ...], ...]
# }
write_wide_xlsx("for_import.xlsx", a1=wide["a1"], headers=wide["headers"], rows=wide["rows"])
```

或直接用 CLI 工具：
```bash
python convert_export_to_import.py --input export.xlsx --output for_import.xlsx
python convert_export_to_import.py --input export.xlsx --output for_import.xlsx --upload
```

## 5. 测试数据生成

`gen_t_double_test.py` 生成符合导出格式的测试 xlsx。

```bash
# 默认: t_double_13..20, 10000 点, 2026-10-15
python gen_t_double_test.py

# 自定义: t_double_21..30, 1000 点, 2026-11-01
python gen_t_double_test.py 21 10 1000 2026-11-01 my.xlsx
```

参数：起始 tag 号, tag 数, 点数, 起始日期, 输出文件名

**生成的数据格式**：
- 每个 cell 的 data_type=`'s'`（字符串）
- Tag Value 是 `'99.0'` 字符串（带 .0）
- 时间方向：倒序
- Quality: 192

**完全匹配** 真实平台导出（`data_type='s'`, `'99.0'` 格式），不是数字。

## 6. 平台宽容性（重要发现）

经过多次验证，平台对导入格式很宽容：

| 输入 | 平台接受 | 备注 |
|---|---|---|
| `yyyy/MM/dd HH:mm:ss` | ✅ | 唯一接受的时间格式 |
| `yyyy-MM-dd HH:mm:ss` | ❌ | 静默失败（HTTP 200 但 0 点）|
| Tag Value = 数字 | ✅ | 强转为对应 dataType |
| Tag Value = 字符串（数字）| ✅ | 解析为数字 |
| Tag Value = 字符串（无法解析）| ❌ | 静默丢弃，不报错 |
| Tag Value = 字符串（"abc"）| ❌ | 静默丢弃 |
| Tag Value = 布尔 (True/False) | ❌ | 静默丢弃 |
| Tag Value = 字符串（科学记数 "1e2"）| ✅ | 解析为 100.0 |
| 时间方向：正序 | ✅ | |
| 时间方向：倒序 | ✅ | 平台按时间正确存储 |
| 活 cron `0/5 * * * * ?` | ✅ | 立即触发 |
| 占位 cron `0 0 0 1 1 ?` | ❌ | 不触发导入流程 |

**关键提醒**：**无效值会被静默丢弃**，HTTP 200 仍返回成功。要查回 `getHistoryValueFromDB` 才能确认实际落地。

## 7. 数据流示意

```
┌─────────────────────┐                  ┌─────────────────────┐
│  平台导出 (long)      │                  │  平台导入 (wide)      │
├─────────────────────┤                  ├─────────────────────┤
│ Sheet: aa_float      │                  │ Sheet: history       │
│ ┌───┬───┬───┬───┐   │                  │ A1: 元信息 4 段       │
│ │TT │AT │Q  │TV │   │   convert.py     │ A2: (空)            │
│ │...│...│...│...│   │ ───────────────> │ B1: aa_float        │
│ │TT │AT │Q  │TV │   │                  │ ...                 │
│ └───┴───┴───┴───┘   │                  │ A3: 2026/06/23 00:00│
│                     │                  │ B3: 0               │
│ Sheet: aa_double     │                  │ ...                 │
│ ...                 │                  │                     │
└─────────────────────┘                  └─────────────────────┘
       ↑                                          ↓
       │                                     platform
       │ read_all_sheets()                    importTagValueHistory
       │ (xlsx_io.py)                        (common_api.py)
       │                                     POST + file
```

## 8. 编码与字符

- **文件编码**：UTF-8（无 BOM）
- **xlsx 单元格类型**：
  - 时间：`'s'`（字符串）—— 即使 Excel 显示为日期，平台读出来是字符串
  - Tag Value：导出是 `'s'`（字符串），导入可以是 `'n'`（数字）或 `'s'`
- **中文**：表头的中文（如 "Tag Time"）保持原样
- **特殊字符**：sheet 名（= tag 名）只允许 ASCII 字母数字下划线

## 9. 大小估算

| 点数 / tag | xlsx 大小 (long, 11 tag) | xlsx 大小 (wide, 11 tag) |
|---|---|---|
| 1000 | ~30 KB | ~50 KB |
| 10000 | ~200 KB | ~1.4 MB |
| 100000 | ~2 MB | ~14 MB |

**平台限制**：单文件 1 GB（`tag-value-import-api.md`）

**实际使用**：建议 ≤ 100k 点 / tag，工具默认 10k 点 / tag。
