# supcon_io 用户手册

> 把 CSV / xlsx / xls 文件用同一对 `read()` / `write()` 读写，库自动 sniff 编码、分隔符、表头行数；不关心数据在业务上是什么意思。
>
> **当前版本**：v0.1.0
>
> designed by yzc

---

## 1. 这是什么

supcon_io 是一个轻量二维数据集 I/O 库：

- 三个文件格式（`.csv` / `.xlsx` / `.xlsm` / `.xls`）共用一对入口：`read(path)` → `Table`，`write(path, table)` → `None`
- 内部 sniff 编码（utf-8-sig / utf-8 / gbk / gb2312）、分隔符（`,` / `;` / `\t` / `|`）、表头行数（含中文双 header 启发式）
- 只管"文件长什么样"，**没有业务语义**：不管位号、容器、OPC UA，单位、量程、命名约定一概不管
- 附赠 `parse_time(s)` 和 `ExcelPrecisionError`，方便在读完之后做时间/精度相关的二次处理

> 与 `ua_player` 等业务库是上下游关系：`supcon_io` 只产出 `Table`，业务库在此之上注入语义。

---

## 2. 使用入门

supcon_io 没有 `setup.py` / `pyproject.toml` 的发布版本（v0.1.0），按仓库源码直接 import。

### 2.1 安装依赖

```bash
pip install openpyxl xlrd==1.2.0 xlwt python-dateutil
```

| 依赖           | 用途                       |
| ------------ | ------------------------ |
| `openpyxl`   | 读 / 写 `.xlsx`、`.xlsm`   |
| `xlrd==1.2.0` | 读 `.xls`（2.x 已不支持 xlsx） |
| `xlwt`       | 写 `.xls`                  |
| `python-dateutil` | `parse_time` 解析字符串时间 |

### 2.2 让 import 找得到库

`supcon_io/` 在仓库根下的子目录里。三种方式任选：

**方式 A：把仓库根加进 `sys.path`（最常用）**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from supcon_io import read, write, Table
```

**方式 B：环境变量 `PYTHONPATH`**

```bash
export PYTHONPATH="/path/to/supcon_tools:$PYTHONPATH"
python your_script.py
```

**方式 C：当成包直接放进工程**（复制 `supcon_io/` 到自己项目里）

> 不要试图 `pip install supcon_io`，v0.1.0 还没发包。

### 2.3 5 行上手

读、改、写一个 CSV：

```python
from supcon_io import read, write

table = read("data.csv")                              # 自动 sniff 编码、分隔符、表头
table.data[0].append("new_col_value")                  # 在第一行末尾加一格
write("data_modified.csv", table)                     # 写回去
```

---

## 3. 公共 API 概览

顶层导出（`from supcon_io import ...`）：

| 名字                  | 类型                     | 说明                                       |
| ------------------- | ---------------------- | ---------------------------------------- |
| `read(path, **kw)`   | 函数                     | 读文件，按扩展名分发，返回 `Table`                   |
| `write(path, table, **kw)` | 函数                | 写文件，按扩展名分发，无返回值                         |
| `Table`             | `NamedTuple`           | `(title: list[str], desc: list[str] \| None, data: list[list[Any]])` |
| `parse_time(value)`  | 函数                     | 把 str / datetime 解析为 `datetime`，失败返回 `None` |
| `ExcelPrecisionError` | 异常类（继承 `ValueError`）   | `excel_numeric_handling='forbid'` 时遇到数字 cell 抛出 |

### 3.1 `read(path, **kwargs) -> Table`

签名：

```python
def read(
    path: str | Path,
    *,
    encoding: str | None = None,
    encoding_hints: tuple[str, ...] = ("utf-8-sig", "utf-8", "gbk", "gb2312"),
    delimiter: str | None = None,
    delimiter_candidates: tuple[str, ...] = (",", ";", "\t", "|"),
    line_terminator: str = "\r\n",
    header_rows: int | None = None,
    skip_blank_lines: bool = True,
    excel_numeric_handling: str = "forbid",
    sniff: bool = True,
) -> Table: ...
```

按扩展名分派：

| 扩展名               | 走哪个内部实现 | 用的库                                |
| ----------------- | ------- | ---------------------------------- |
| `.csv`            | `_read_csv` | `csv`（stdlib）                       |
| `.xlsx` / `.xlsm` | `_read_xlsx` | `openpyxl`（lazy import）              |
| `.xls`            | `_read_xls`  | `xlrd 1.2.0`（lazy import）            |
| 其它                | 抛 `ValueError` | —                                  |

> 单元格类型差异：CSV → `str`；xlsx/xls → `openpyxl` / `xlrd` 原生类型（`int` / `float` / `datetime` / `str` / `None`）。

### 3.2 `write(path, table, **kwargs) -> None`

签名：

```python
def write(
    path: str | Path,
    table: Table,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
    line_terminator: str = "\r\n",
    header_rows: int = 1,
    sheet_name: str = "Sheet1",
) -> None: ...
```

| 扩展名               | 内部实现      | 关键点                                                       |
| ----------------- | --------- | -------------------------------------------------------- |
| `.csv`            | `_write_csv` | `None` 写为空字符串；`encoding` 默认 `utf-8`；`delimiter` 默认 `,`        |
| `.xlsx` / `.xlsm` | `_write_xlsx` | `sheet_name` 默认 `Sheet1`；`header_rows >= 2` 且 `table.desc` 不为 `None` 才写第 2 行 |
| `.xls`            | `_write_xls`  | 全部转 `str` 后写；`xlwt` 不支持原生数字/日期类型                       |

> `table.desc is None` 时，无论 `header_rows` 传几，都强制按 1 行表头写。

### 3.3 `Table(title, desc, data)`

```python
class Table(NamedTuple):
    title: list[str]
    desc: list[str] | None
    data: list[list[Any]]
```

| 字段    | 类型                  | 含义                                       |
| ----- | ------------------- | ---------------------------------------- |
| title | `list[str]`         | 第 1 行表头列名；无表头时为 `[]`                  |
| desc  | `list[str] \| None` | 第 2 行描述（双 header 时）；单行 / 无表头时为 `None`     |
| data  | `list[list[Any]]`   | 数据行，每行一个 `list`；元素类型随文件源（CSV 全 `str`） |

构造示例：

```python
from supcon_io import Table

t = Table(
    title=["timeStamp", "temperature"],
    desc=["时间戳", "温度"],
    data=[
        ["2024/06/30 12:00:00", "25.5"],
        ["2024/06/30 12:00:01", "26.0"],
    ],
)
```

### 3.4 `parse_time(value) -> datetime | None`

```python
from datetime import datetime
from supcon_io import parse_time

parse_time("2024/06/30 12:00:00")     # → datetime(2024, 6, 30, 12, 0)
parse_time(datetime(2024, 6, 30))     # → 原样返回
parse_time("")                        # → None
parse_time(None)                      # → None
parse_time("not a time")              # → None（解析失败兜底）
```

承诺 cover 的 2 种格式（带秒）：

- `2024/06/30 12:00:00`
- `2024-06-30 12:00:00`

赠送 cover（不承诺，依赖 `dateutil.parser`）：

- ISO 8601：`2024-06-30T12:00:00`
- 含微秒：`2024-06-30 12:00:00.123456`
- 单位数月日：`2024/6/3 19:00:00`
- 纯日期：`2024-06-30`（默认 `00:00`）

> epoch 数字串（`1719748800` 这种）不 cover，返回 `None`。

### 3.5 `ExcelPrecisionError`

继承自 `ValueError`。`read()` xlsx / xls 时若数据行出现 `int` / `float`，且 `excel_numeric_handling='forbid'`（默认），就抛它。

捕获示例：

```python
from supcon_io import read, ExcelPrecisionError

try:
    table = read("report.xlsx")
except ExcelPrecisionError as e:
    print("命中数字 cell:", e)
    table = read("report.xlsx", excel_numeric_handling="allow")
```

---

## 4. 功能介绍

### 4.1 sniff：read 自动探测的参数

`read()` 默认 `sniff=True`，下列参数传 `None` 就会自动嗅探；显式传值则跳过对应项。

| 参数                  | sniff 时怎么算                                                                                | 用户显式传则           |
| ------------------- | ---------------------------------------------------------------------------------------- | --------------- |
| `encoding`          | 先看 BOM（utf-8-sig / utf-16-le / utf-16-be），再用 `encoding_hints` 顺序试，能 decode 的第一个胜出 | 用传入的编码           |
| `delimiter`         | 在前 4096 字节里统计 `delimiter_candidates` 各候选的出现次数，选"行间方差最小 + 平均 ≥ 0.5"的               | 用传入的分隔符          |
| `header_rows`       | 拆出第 1 / 2 行：列数相同 **且** 第 2 行汉字比例 ≥ 60% 视为双行；否则单行（`header_rows=2`）                | 用传入的行数           |
| `excel_numeric_handling` | 走默认 `forbid`                                                                          | —               |

> sniff 失败（编码 / 分隔符都无法识别）会兜底：编码 → `utf-8`，分隔符 → `,`，`header_rows` → `1`。显式传的值不受兜底影响。

中文双 header 嗅探示例（详见 4.2 节）：

```csv
timeStamp,温度,压力
时间戳,摄氏度,MPa
2024/06/30 12:00:00,25.5,0.1
```

→ `header_rows=2`，`title=['timeStamp','温度','压力']`，`desc=['时间戳','摄氏度','MPa']`，`data=[['2024/06/30 12:00:00','25.5','0.1']]`。

### 4.2 sniff 规则的边界与坑

**中文双 header 启发式只认汉字行**

如果第 2 行是英文描述（如 `timestamp, value`），汉字比例 < 60%，会被判为单行 header。若你确实有英文双 header，必须显式传 `header_rows=2`：

```python
table = read("double_header_en.csv", header_rows=2)
```

**GBK / GB2312 嗅探**

`encoding_hints` 默认包含 `gbk` 和 `gb2312`，中文 Windows 导出的 CSV（无 BOM）通常会被自动命中。嗅探优先级：先 BOM → 再 hints 顺序（`utf-8-sig` → `utf-8` → `gbk` → `gb2312`）。

**`skip_blank_lines`**

默认 `True`。空行（只有空白字符的行）从数据中剔除。若你的文件用空行做分隔，且希望保留为数据行，传 `skip_blank_lines=False`。

**`sniff=False`**

跳过 sniff，所有需要嗅探的项**必须**显式传，否则用兜底值（`encoding='utf-8'`、`delimiter=','`、`header_rows=1`）。这在脚本需要稳定可重复、不依赖文件内容变化时有用。

### 4.3 `excel_numeric_handling` 三种策略

仅作用于 xlsx / xls 的读路径，写路径不区分（写出去都是字符串 / openpyxl 原生类型）。

| 策略                | 数据行遇到 `int` / `float` 时                                              | 适用场景                                   |
| ----------------- | -------------------------------------------------------------------- | -------------------------------------- |
| `forbid`（**默认**）   | 抛 `ExcelPrecisionError`                                              | 业务上数字不该来自 Excel，要杜绝 15 位浮点精度漂移到下游 |
| `allow`           | 原样保留为 `int` / `float`                                                | 明确接受 Excel 浮点（精度会受 Excel 存储格式影响）    |
| `force_text`      | 抛 `ExcelPrecisionError`（**仅 forbid/allow 实现，force_text 当前按 forbid 走**） | —                                      |

> **为什么要默认 `forbid`？** Excel 把数字存为双精度浮点（IEEE 754），与 Python `int` / `float` 来回转换时常见的 `25.500000000000004` 这类精度漂移很难在下游定位。`forbid` 让"数据来自 Excel 数字列"这件事在 read 时就显式炸出来，强制调用方决定接受 / 兜底。

`bool` 视为合法（bool 是 int 子类，但语义上是开/关），`datetime` / `date` 视为合法（不算"数字"），`None` / `str` 也合法。

### 4.4 单元格类型

| 来源          | 元素类型                                                            |
| ----------- | --------------------------------------------------------------- |
| `.csv`      | 全部 `str`（数字 / 时间都是字符串，调用方按需 `parse_time` / `int` / `float`） |
| `.xlsx`     | openpyxl 原生类型：`int` / `float` / `datetime` / `str` / `None`     |
| `.xls`      | xlrd 原生类型；`XL_CELL_DATE` 转 `datetime`，其它保留原值                |

> 写 CSV 时 `None` 会被写成空字符串；写 xlsx / xls 时 `None` 也写成空字符串（不做单元格清空处理）。

### 4.5 不支持的格式

- `.json` / `.parquet` / `.tsv`（虽然能存为 CSV 用 `\t` 分隔）
- `.xlsb`（Excel 二进制）
- 任何不带扩展名或扩展名不在白名单的文件

调用结果：抛 `ValueError("不支持的扩展名: <suffix>, 仅支持 .csv/.xlsx/.xlsm/.xls")`。

### 4.6 性能注意

- **lazy import**：`openpyxl` / `xlrd` / `xlwt` 在第一次真正用到时才 import。纯 CSV 场景启动不会被这三个库拖慢。
- **xlsx 大文件**：`read` 用 `read_only=True, data_only=True`，流式读取；但库本身不切片，全文件 load 进内存后再切表头。超大文件（>100MB）请自己评估内存。
- **sniff 读 4096 字节**：仅嗅探前 4KB，编码 / 分隔符判完后用嗅探到的编码读全文。header_rows sniff 也只用前若干行。

### 4.7 已知坑

**Excel 浮点精度漂移**

25.5 在 xlsx 里存的是 25.5，但 25.50000001 这种读出来可能变 25.500000010000001。`forbid` 让你在源头显式决策，**默认推荐保持 `forbid`**。

**中文双 header**

只认汉字行（第 2 行汉字 ≥ 60%）。英文双 header 一定显式 `header_rows=2`。

**GBK 文件大小写**

`encoding_hints` 默认含 `gbk` 和 `gb2312`，命中顺序按 hints；不传 hints 就会被试到。Windows 导出的 `ANSI` / `GB18030` 通常被 `gbk` 兜住。

**xls 写丢类型**

`xlwt` 只支持 `str`，所以 `table.data` 里的 `int` / `float` / `datetime` 写 xls 时会先 `str(v)`。需要数字落盘就写 xlsx / csv。

**xls `XL_CELL_DATE`**

值为 `0.0` 时（Excel 序列起点）会被原样保留成 `0.0`，**不**转 `datetime`。

---

## 5. 完整可用示例

### 5.1 读 / 写 CSV

```python
from supcon_io import read, write, Table

# 读:全 sniff
table = read("data.csv")
print(table.title)   # ['timeStamp', 'temperature']
print(table.data[0]) # ['2024/06/30 12:00:00', '25.5']

# 读:显式参数,关闭 sniff
table = read("data.csv", sniff=False, encoding="utf-8", delimiter=",", header_rows=1)

# 写:默认 utf-8 + ,
out = Table(
    title=["timeStamp", "device"],
    data=[["2024/06/30 12:00:00", "R101"]],
)
write("out.csv", out)

# 写:GBK + ;
write("out_gbk.csv", out, encoding="gbk", delimiter=";")
```

### 5.2 读 / 写 xlsx

```python
from supcon_io import read, write, ExcelPrecisionError

# 读:纯文本 cell,默认 forbid 不抛
table = read("report.xlsx")
for row in table.data:
    print(row)

# 读:遇到数字 cell → 抛 ExcelPrecisionError
try:
    read("report_with_numbers.xlsx")
except ExcelPrecisionError as e:
    print("命中数字:", e)
    table = read("report_with_numbers.xlsx", excel_numeric_handling="allow")

# 写:自定义 sheet 名
write("new_report.xlsx", table, sheet_name="Data")
```

### 5.3 读 xls

```python
from supcon_io import read, ExcelPrecisionError

# 读 2003 格式
table = read("legacy.xls")

# 数字 cell 同样会触发 ExcelPrecisionError(forbid)
try:
    read("legacy_with_numbers.xls")
except ExcelPrecisionError:
    table = read("legacy_with_numbers.xls", excel_numeric_handling="allow")
```

> xls 写路径用 `xlwt`，所有值会被转 `str`。

### 5.4 中文双 header CSV

```csv
timeStamp,温度,压力
时间戳,摄氏度,MPa
2024/06/30 12:00:00,25.5,0.1
2024/06/30 12:00:01,26.0,0.1
```

```python
from supcon_io import read

table = read("zh_double.csv")  # 自动 sniff header_rows=2
assert table.title == ["timeStamp", "温度", "压力"]
assert table.desc == ["时间戳", "摄氏度", "MPa"]
```

### 5.5 GBK CSV

```python
from supcon_io import read

# sniff 自动命中 gbk
table = read("chinese_windows.csv")
assert table.data[0][1] == "反应釜R101"

# 也可显式传
table = read("chinese_windows.csv", encoding="gbk")
```

### 5.6 `parse_time` 时间解析

```python
from supcon_io import read, parse_time

table = read("timeseries.csv")
for row in table.data:
    ts = parse_time(row[0])  # row[0] 是 str
    if ts is not None:
        print(ts.year, ts.month, ts.day)
```

### 5.7 `ExcelPrecisionError` 处理

```python
from supcon_io import read, ExcelPrecisionError

for candidate in ["report.xlsx", "report_legacy.xls"]:
    try:
        table = read(candidate)
    except ExcelPrecisionError as e:
        # 命中数字 cell:打印位置 + 重试 allow
        print(f"{candidate}: {e}")
        table = read(candidate, excel_numeric_handling="allow")
    print(candidate, len(table.data), "rows")
```

### 5.8 不支持的扩展名

```python
from supcon_io import read

try:
    read("data.json")
except ValueError as e:
    print(e)  # 不支持的扩展名: .json, 仅支持 .csv/.xlsx/.xlsm/.xls
```

---

designed by yzc