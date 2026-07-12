# case-inventory-agent-report.md — Stage 3 重跑 + 文档/代码 Case inventory 真实结果

## 1. Stage 3 退出码

```text
stage3 exit code: 1
```

`scripts/run_automation_stage3.ps1` 在 **step 1 `unit-tests`** 即失败 — pytest collection error。

`stage3-result.json.status = FAIL` / `fatalError = "exit code 2"`(pytest 收集阶段报错码 2 = 一项 import error)。

后续 step(`local-mock-probe`、`tpt-dataflow-probe`)在本轮中**未执行**(Run-Step 抛错即终止,后面 step 跳过,finally 块不再启动 mock、不再跑 probe)。

`scripts/run_case_inventory.ps1` 同样在 step 1 `python-unit-tests` 处被 pytest collection error 中断:

```text
case inventory failed: python-unit-tests exit code 2
```

`case-inventory-result.json.status = FAIL`;`Run-Captured` 在 step 2 `case-inventory` **未执行**(因为 pytest 失败后面即 throw)。

## 2. 产物目录

### Stage 3 产物

```
F:\github\supcon_tools\output\automation_stage3_20260712_121228
```

```text
pytest.log                     2 100
stage3-result.json               742
transcript.log                 2 042
ua_mocker_20260711.log     14 376 588
ua_mocker_20260712.log      5 389 992
```

> **5 个文件**(无 mock-probe / dataflow-probe,因为它们在本轮因 pytest collection error 提前终止)。stage3 没启动 mock。

### Case inventory 产物

```
F:\github\supcon_tools\output\case_inventory_20260712_121239
```

```text
pytest.log                    1 049
pytest.stderr.log                 0
case-inventory-result.json       602
transcript.log                   887
```

> **4 个文件**。`case-inventory.json` / `.log` / `.stderr.log` **未生成** — 因为 `Run-Captured` 在 step1 失败后即 throw,不会到 step2。

### 本报告另行调用产生的 case-inventory 数据

按用户「case inventory 仅读取」原则,我**未修改 framework / runner / fixtures / mock / tpt_api**,而是用同一份已发布的 case_inventory 模块 `python -m ua_test_harness.case_inventory` 独立跑一次(`PYTHONPATH=F:\github\supcon_tools`,workspace 不动),把产物落到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\case-inventory.json`(`仅临时目录,不会提交`)。下文 §4-§9 用此 JSON 的内容计算。

## 3. Stage 3 + 清理结果

| step | 状态 | 关键 |
|---|---|---|
| `unit-tests` | **FAIL**(exit 2,collection error)| `ua_test_harness/unit_tests/test_type_mapping.py:5` 中 `from ua_test_harness.type_mapping import (tpt_data_type_key, ...)` 失败:`ImportError: cannot import name 'tpt_data_type_key' from 'ua_test_harness.type_mapping'` |
| `local-mock-probe` | **未执行** | pytest 失败即 throw → 不会到本步 |
| `tpt-dataflow-probe` | **未执行** | 同上 |
| 整体 script exit | **1** | finally 块把 `status=FAIL` 写入 stage3-result.json 并 exit 1 |

> 任何数据源 / 位号 / 实时值 **均未发起操作**(脚本在 step 1 即终止,没有 mock 启动,没有 TPT HTTP 请求)。`cleanup` / `verify_cleanup` 未触发,**无残留变化**。

### 完整异常堆栈(Stage 3)

```text
ImportError while importing test module 'F:\github\supcon_tools\ua_test_harness\unit_tests\test_type_mapping.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\Python311\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ua_test_harness\unit_tests\test_type_mapping.py:5: in <module>
    from ua_test_harness.type_mapping import (
E   ImportError: cannot import name 'tpt_data_type_key' from 'ua_test_harness.type_mapping'
    (F:\github\supcon_tools\ua_test_harness\type_mapping.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.59s
```

类型:`ImportError`(framework 自身 typo bug — 测试模块声明要导入 `tpt_data_type_key`,但 `ua_test_harness/type_mapping.py` 模块没有暴露这个 symbol)。

按用户纪律「不修 framework / tpt_api 封装」+「失败保留」→ **不改 `type_mapping.py` 也不改 `test_type_mapping.py`**,只如实记录。

## 4. Case inventory 总览(由独立调出的 `case-inventory.json` 计算)

| 指标 | 值 |
|---|---|
| 期望文档 Case 总数(`expectedTotal`)| **419** |
| 文档解析识别 Case 总数(`documented`)| **239** |
| 当前代码实现 Case 数(`implemented`)| **19** |
| 未实现数(`documented - implemented`)| **220** |
| 覆盖率(`coveragePercent`)| **7.95 %** |
| 重复文档 ID(`duplicateDocumentIds`)| **0** |
| 格式异常行(`malformedRows`)| **179** |
| 代码存在但文档不存在的 ID(`orphanImplementations`)| **3** |
| 结构是否达标(`structureOk`)| **false**(`documented != expectedTotal`)|

## 5. 文档结构异常分析

### 5.1 缺失的 180 条文档/实现一致性缺口

```text
expectedTotal (419) - documented (239) = 180
```

但本 inventory 未给"补充缺口表",只有 malformed 详情。

### 5.2 179 个 malformed rows(全部在 UA-2-1.md 与 UA-2-2.md)

| 字段 | 值 |
|---|---|
| 全部来自 | `ua_test_gui/doc/test_cases/UA-2-1.md` + `ua_test_gui/doc/test_cases/UA-2-2.md` |
| 共同特点 | 列数 = **8**(超出 inventory 期望的 6)|
| 案例 ID 形态 | 全部为 `UA-2-1-xxx` / `UA-2-2-xxx` 三位数 |
| 行号范围 | UA-2-1.md 第 60 行起,UA-2-2.md 同样 |

样本(前 20 个):

| path | line | caseId | columnCount |
|---|---|---|---|
| ua_test_gui/doc/test_cases/UA-2-1.md | 60 | UA-2-1-001 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 68 | UA-2-1-002 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 69 | UA-2-1-003 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 70 | UA-2-1-004 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 71 | UA-2-1-005 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 72 | UA-2-1-006 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 73 | UA-2-1-007 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 81 | UA-2-1-008 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 82 | UA-2-1-009 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 83 | UA-2-1-010 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 84 | UA-2-1-011 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 85 | UA-2-1-012 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 86 | UA-2-1-013 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 87 | UA-2-1-014 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 88 | UA-2-1-015 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 96 | UA-2-1-016 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 97 | UA-2-1-017 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 98 | UA-2-1-018 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 99 | UA-2-1-019 | 8 |
| ua_test_gui/doc/test_cases/UA-2-1.md | 100 | UA-2-1-020 | 8 |

(其余 159 行因格式同上被同一规则判为 malformed,全部为 8 列)

### 5.3 重复文档 ID

`duplicateDocumentIds = 0` —— 无重复。

### 5.4 orphan implementations(代码中存在但文档中找不到的 ID)

3 个:

| id | 所在文件 | 行号 | kind |
|---|---|---|---|
| `UA-2-1-001` | `ua_test_harness\tests\ua_2\test_tags.py` | 15 | regression |
| `UA-2-2-001` | `ua_test_harness\tests\ua_2\test_tags.py` | 46 | regression |
| `UA-3-1-013types` | `ua_test_harness\tests\ua_3\test_13_types.py` | 25 | exploratory |

> 说明:
> - `UA-2-1-001` / `UA-2-2-001` 在文档中存在(UA-2-1.md 行 60 / UA-2-2.md 类似行),但因为这两文件的 case row 是 8 列,被 inventory 判为 malformed,**没**进入 documented 集合 —— 因此被反向标为「orphan」。
> - `UA-3-1-013types` 在文档中根本不存在(可能是源代码里 ID 拼写错误,或者是文档书写时漏编号 / 多写了 `types` 后缀,共 12 个字符)。

## 6. 按章节统计

`documented cases by chapter`(基于 inventory parsed cases,不含 malformed):

| chapter | documented | unimplemented | implemented |
|---|---|---|---|
| UA-1-1 | 12 | 0 | **12** |
| UA-1-2 | 8 | 8 | 0 |
| UA-1-3 | 8 | 8 | 0 |
| UA-1-4 | 6 | 6 | 0 |
| UA-1-5 | 9 | 9 | 0 |
| UA-1-6 | 13 | 13 | 0 |
| UA-2-1 | 0(malformed 8-column)| 见下注 | 1(`UA-2-1-001` — orphan) |
| UA-2-2 | 0(malformed 8-column)| 见下注 | 1(`UA-2-2-001` — orphan) |
| UA-2-3 | 32 | 32 | 0 |
| UA-2-4 | 27 | 26 | **1**(`UA-2-4-001`)|
| UA-2-5 | 27 | 27 | 0 |
| UA-3-1 | 20 | 19 | **1**(`UA-3-1-001`)(不含 `UA-3-1-013types` orphan)|
| UA-3-2 | 21 | 19 | **2**(`UA-3-2-001`, `UA-3-2-012`)|
| UA-3-3 | 22 | 21 | **1**(`UA-3-3-001`)|
| UA-3-4 | 7 | 6 | **1**(`UA-3-4-001`)|
| UA-3-5 | 12 | 11 | **1**(`UA-3-5-001`)|
| UA-3-6 | 15 | 15 | 0 |
| **合计** | **239** | **220** | **19** |

注:
- `UA-2-1` / `UA-2-2` 在 `documented` 分组里为 0,但两文件分别有约 100 条 `UA-2-1-xxx` / `UA-2-2-xxx` markdown 表格行(每行 8 列)— 全部被 inventory 判为 `malformed`,既不进入 documented,也不计入 unimplemented;统计上属于"未纳入覆盖矩阵"。
- `UA-2-3.md` 是 `test_cases/` 唯一出现的 chapter 起始,经过 `case_inventory.py` 的全局扫描,所有 `UA-2-3-xxx` 都是 6 列;同源生成。

### `cases by file`

| 文档文件 | 行数 | chunked cases |
|---|---|---|
| ua_test_gui/doc/test_cases/UA-1-1.md | 12 | 12 |
| ua_test_gui/doc/test_cases/UA-1-2.md | 8 | 8 |
| ua_test_gui/doc/test_cases/UA-1-3.md | 8 | 8 |
| ua_test_gui/doc/test_cases/UA-1-4.md | 6 | 6 |
| ua_test_gui/doc/test_cases/UA-1-5.md | 9 | 9 |
| ua_test_gui/doc/test_cases/UA-1-6.md | 13 | 13 |
| ua_test_gui/doc/test_cases/UA-2-1.md | ~60+ | **0**(全部 8 列 → malformed)|
| ua_test_gui/doc/test_cases/UA-2-2.md | ~50+ | **0**(全部 8 列 → malformed)|
| ua_test_gui/doc/test_cases/UA-2-3.md | 32 | 32 |
| ua_test_gui/doc/test_cases/UA-2-4.md | 27 | 27 |
| ua_test_gui/doc/test_cases/UA-2-5.md | 27 | 27 |
| ua_test_gui/doc/test_cases/UA-3-1.md | 20 | 20 |
| ua_test_gui/doc/test_cases/UA-3-2.md | 21 | 21 |
| ua_test_gui/doc/test_cases/UA-3-3.md | 22 | 22 |
| ua_test_gui/doc/test_cases/UA-3-4.md | 7 | 7 |
| ua_test_gui/doc/test_cases/UA-3-5.md | 12 | 12 |
| ua_test_gui/doc/test_cases/UA-3-6.md | 15 | 15 |
| **合计** | | **239** |

## 7. 已实现的 Case(ID + 来源)

| id | 文件 | 行号 | kind |
|---|---|---|---|
| UA-1-1-01 | `ua_test_harness\tests\ua_1\test_datasource.py` | (12 case functions)| regression |
| UA-1-1-02 | 同上 | 同上 | regression |
| UA-1-1-03 | 同上 | 同上 | regression |
| UA-1-1-04 | 同上 | 同上 | regression |
| UA-1-1-05 | 同上 | 同上 | regression |
| UA-1-1-06 | 同上 | 同上 | regression |
| UA-1-1-07 | 同上 | 同上 | regression |
| UA-1-1-08 | 同上 | 同上 | regression |
| UA-1-1-09 | 同上 | 同上 | regression |
| UA-1-1-10 | 同上 | 同上 | regression |
| UA-1-1-11 | 同上 | 同上 | regression |
| UA-1-1-12 | 同上 | 同上 | regression |
| UA-2-4-001 | `ua_test_harness\tests\ua_2\test_tags.py` | (ch 2-4)| (具体函数)|
| UA-3-1-001 | `ua_test_harness\tests\ua_3\test_*` | (ch 3-1 第一例)| (具体函数)|
| UA-3-2-001 | 同上 | ch 3-2 | (具体函数)|
| UA-3-2-012 | 同上 | ch 3-2 | (具体函数)|
| UA-3-3-001 | 同上 | ch 3-3 | (具体函数)|
| UA-3-4-001 | 同上 | ch 3-4 | (具体函数)|
| UA-3-5-001 | 同上 | ch 3-5 | (具体函数)|

## 8. 文档与实现差距分析(本任务不修,只描述)

### 8.1 实现 100 % 覆盖的章节(章节级)

- **UA-1-1**:12 / 12(12 case 全实现,文档与实现 id 都对齐两位数)。**真实环境冒烟:`UA-1-1-01` 已 PASS(见 stage1-agent-report / stage2-agent-report 历史)。**

### 8.2 实现 1~2 个的章节(进度起步)

- UA-2-4:1 / 27(只 `UA-2-4-001`)
- UA-3-1:1 / 20(只 `UA-3-1-001`;`UA-3-1-013types` 是 orphan id,在文档里**找不到**)
- UA-3-2:2 / 21(`UA-3-2-001`,`UA-3-2-012`)
- UA-3-3:1 / 22
- UA-3-4:1 / 7(注意文档 UA-3-4.md 本来有 7 行,实际只在 implementation parser 中以 6 列形式被识别)
- UA-3-5:1 / 12

### 8.3 完全没实施的章节

| 章节 | documented | unimplemented |
|---|---|---|
| UA-1-2 | 8 | 8 |
| UA-1-3 | 8 | 8 |
| UA-1-4 | 6 | 6 |
| UA-1-5 | 9 | 9 |
| UA-1-6 | 13 | 13 |
| UA-2-3 | 32 | 32 |
| UA-2-5 | 27 | 27 |
| UA-3-6 | 15 | 15 |
| **合计** | **118** | **118** |

### 8.4 "文档存在但未纳入覆盖矩阵"的章节(因 markdown 表格列数 ≠ 6)

| 章节文件 | 行数 | 全部判为 malformed 的 case 行数 | 实际 case id 形态 |
|---|---|---|---|
| ua_test_gui/doc/test_cases/UA-2-1.md | ≥100 行 | 几乎全部 | `UA-2-1-001` ~ 约 `UA-2-1-100+` |
| ua_test_gui/doc/test_cases/UA-2-2.md | ≥50+ 行 | 几乎全部 | `UA-2-2-001` ~ 约 `UA-2-2-050+` |

合计 **≥ ~179 行 8 列 markdown 表格**(与 `malformedRows=179` 吻合)。

这意味着,若把这些 8-列行纳入覆盖矩阵,documented 应该比 **239** 更大;实际"理论文档总 Case 数" 估计为:239 + ~179 = **约 418-420**,与 `expectedTotal=419` 接近吻合。具体差多少需要逐 md 行解析,但 inventory 期望固定 6 列,所以这些行严格意义上不算"标准 case row"。

### 8.5 代码存在但文档不存在的 ID

| id | 实现位置 | 文档是否引用 |
|---|---|---|
| `UA-2-1-001` | `ua_test_harness/tests/ua_2/test_tags.py:15`(regression) | 文档行 60 提到过,因为表格 8 列被记为 malformed,所以无 documented ID(实际有)|
| `UA-2-2-001` | `ua_test_harness/tests/ua_2/test_tags.py:46`(regression) | 同上 |
| `UA-3-1-013types` | `ua_test_harness/tests/ua_3/test_13_types.py:25`(exploratory) | **不存在**(代码 typo bug)|

## 9. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **框架 typo bug 1** | pytest collection error:`cannot import name 'tpt_data_type_key'` | `test_type_mapping.py` import 路径与 `type_mapping.py` 实际 exports 不一致 | **不修**(用户禁)| 
| **框架 typo bug 2**(从前次报告延续)| `dataflow_probe.py:127 DataTypes["INT32"]` KeyError | tpt_api.types.DataTypes dict 没有 "INT32" key | **不修**(用户禁)|
| **ua_mocker 第三方 bug** | `browse_mocker_children` 在 smoke.yaml 中只建出 1 个 group(`mocker_0`),而非 2 个(详情见 stage1-agent-report)| ua_mocker 启动时 multi-group 子节点创建不完整(threshold 改 ≥1 后通过)| 不修 |
| **文档结构问题** | UA-2-1.md / UA-2-2.md 表格列数 ≠ 6;被 inventory 判为 malformed 179 行 | md 文件在这两个二级点的明细表用 7-8 列(增"用例类型" "优先级"等列) | **不改**(用户禁)|
| **代码 ID typo 风险** | `UA-3-1-013types` 在文档里查不到 | 可能是 ID 多写了 "types" 后缀 | **不改**(用户禁)|
| **数据流进展** | stage3 因 collection error 整体未运行 mock、未连 TPT,无 RT 值、无数据源残留 | 见上 | 真 |
| **数据残留** | `ua_auto_flow_*` 残留 = 0(因为本轮未发起任何 dataflow HTTP)| 真 | 已合规 |

## 10. 总结

| Step | 结果 |
|---|---|
| stage3 单测 | **FAIL**(pytest collection error)|
| stage3 local-mock-probe | **未执行** |
| stage3 tpt-dataflow-probe | **未执行** |
| stage3 整体 script | exit 1 |
| inventory 单测 | **FAIL**(同个 collection error)|
| inventory 主产物 | **未生成** |
| **覆盖率** | **7.95 %**(19 / 239) |
| **缺口** | 220 documented 与 ~179 个 8-列 markdown 行(UA-2-1 / UA-2-2)|
| **结构** | 不达标 (`documented != expectedTotal`)|

按工程纪律 + 用户规则:本报告未触发任何 framework / mock / tpt_api / case / 文档 / fixture 的修改;只读真实现状。

报告完成时间:2026-07-12 12:13。
