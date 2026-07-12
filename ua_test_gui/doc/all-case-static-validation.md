# all-case-static-validation.md — 419 Case 静态注册 + inventory 验证(2026-07-12 13:30)

## 1. 用户期望 HEAD

```text
98b7de4162dbb195147daa9dfdf171c4641fb6dc
```

实测 `git rev-parse HEAD`:

```text
98b7de4162dbb195147daa9dfdf171c4641fb6dc
```

✓ 完全匹配。

## 2. 退出码与产物

```text
static validation exit code: 1
```

> `scripts/run_all_case_static.ps1` **自身**中断在 step3 `catalog-export`(framework typo bug,详见 §3),未能继续到 step4 `case-inventory` 与其内置断言。
> 因此以下 §4-§7 的 inventory 数据由本报告**独立手工调用同一份已发布 `python -m ua_test_harness.case_inventory --strict-structure` 拿到**,输出写到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\case-inventory.json`(不提交)。**未改 framework / scripts / case / fixture / assertion。**

### 2.1 脚本产物目录

```
F:\github\supcon_tools\output\all_case_static_20260712_132930
```

| 文件 | 大小 | 来源 |
|---|---|---|
| `all-case-static-result.json` | 1 243 | 脚本主产物 |
| `transcript.log` | 896 | PowerShell Start-Transcript |
| `compile.log` | 0 | compileall -q(stdout 重定向)|
| `compile.stderr.log` | 0 | compileall(stderr)|
| `pytest.log` | 101 | pytest -q |
| `pytest.stderr.log` | 0 | pytest stderr |
| `catalog.log` | 0 | catalog(stdout 重定向)|
| `catalog.stderr.log` | 131 | catalog stderr(输出 framework TypoError)|
| `case-inventory.log` | —(未生成)| step4 未触发 |
| `case-inventory.json` | —(未生成)| step4 未触发 |
| `case-inventory.stderr.log` | —(未生成)| step4 未触发 |

### 2.2 `all-case-static-result.json`

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T13:29:39.2662995+08:00",
  "repoRoot": "F:\\github\\upcon_tools",
  "expectedTotal": 419,
  "steps": [
    { "name": "python-compile",    "status": "PASS", "exitCode": 0, "startedAt": "2026-07-12T13:29:30...", "finishedAt": "2026-07-12T13:29:32..." },
    { "name": "python-unit-tests", "status": "PASS", "exitCode": 0, "startedAt": "2026-07-12T13:29:32...", "finishedAt": "2026-07-12T13:29:38..." },
    { "name": "catalog-export",    "status": "FAIL", "exitCode": 1, "startedAt": "2026-07-12T13:29:38...", "finishedAt": "2026-07-12T13:29:39..." }
  ],
  "fatalError": "catalog-export exit code 1",
  "status": "FAIL"
}
```

## 3. Python 编译是否通过?

**是**(`python-compile` PASS, exit 0)。

| 步骤 | 结果 | 详情 |
|---|---|---|
| `compileall -q ua_test_harness tpt_api` | **PASS** | 0 stderr / 0 stdout(静默成功)|
| `pytest ua_test_harness/unit_tests` | **PASS**(46 passed / 4.24s) | 0 collection error / 0 SyntaxError / 0 ImportError |
| **是否存在 import / collection / SyntaxError?** | **否**(unit_tests 46 全过)| 0 errors / 0 failures |

> 此前(`git log` 上几轮)出现过的 `ImportError: normalize_opcua_type_name` 与 `SyntaxError: unterminated "UINT` 已在 commit `51a9f57 fix(automation): complete OPC UA type mapping api` 修复。本次 main HEAD 已是 51a9f57 + 98b7de4 的 fast-forward,本地上看到的是已经修复后的文件。

## 4. catalog Case 总数是否为 419?

**是**。但脚本自己**没有产出** catalog.json(step3 fail);独立手工调用产出:

```text
catalog written: C:\Users\yuzechao\AppData\Local\Temp\opencode\catalog.json chapters=17 cases=419
```

| 章节 | cases |
|---|---|
| UA-1-1 | 12 |
| UA-1-2 | 8 |
| UA-1-3 | 8 |
| UA-1-4 | 6 |
| UA-1-5 | 9 |
| UA-1-6 | 13 |
| UA-2-1 | 112 |
| UA-2-2 | 67 |
| UA-2-3 | 32 |
| UA-2-4 | 27 |
| UA-2-5 | 27 |
| UA-3-1 | 20 |
| UA-3-2 | 21 |
| UA-3-3 | 22 |
| UA-3-4 | 8 |
| UA-3-5 | 12 |
| UA-3-6 | 15 |
| **合计** | **419**(12+8+8+6+9+13+112+67+32+27+27+20+21+22+8+12+15 = 419)|

## 5. Case ID 是否全部唯一?

**是**(419 unique / 419 total)。

| 总数 | 唯一数 | 重复数 |
|---|---|---|
| 419 | 419 | 0 |

## 6. 每条 Case 是否都有 steps 和 assertions?

**是**(以 catalog.json 自报为准)。

| 维度 | 统计 |
|---|---|
| 全部 419 case 都有 `steps`(长度 1 ~ 7)| 397 case steps=1 / 2 case steps=2 / 4 case steps=3 / 11 case steps=4 / 4 case steps=5 / 1 case steps=7 |
| 全部 419 case 都有 `assertions`(确切 1 个)| **419 / 419** |

> **关于 inventory schema 与 catalog schema 的不一致**:
> inventory 报 `cases[].assertions = 0`,**不能**用来判定 case 没断言 — 因为 `ua_test_harness/case_inventory.py:30-54` 解析 markdown 时只把单元格 `cells[5] = expected` 单存为 `expected` 字段,**没有**把 `expected` 拆成 `assertions` 数组。`case_inventory.py` 也未在 case schema 暴露 `assertions` 字段。
> 因此"每条 case 都有 assertions"的真值以 **`catalog.json` 自报的 `cases[].assertions` 数组**为准:**419 / 419 = 100%**。

## 7. inventory 是否符合预期?

| 指标 | 期望 | 实际(独立 strict-structure)|
|---|---|---|
| documented | 419 | **419** ✓ |
| implemented | 419 | **419** ✓ |
| unimplemented | 0 | **0** ✓ |
| malformed | 0 | **0** ✓ |
| duplicates | 0 | **0** ✓ |
| orphans | 0 | **0** ✓ |
| structureOk | true | **true** ✓ |
| documentWarnings | (无要求)| 1(仅计数)|

> inventory.strict-structure mode 同时校验 `duplicates / malformed / documented==expectedTotal`,**全部通过**(没有输出任何 `STRUCTURE_ERROR:` 行,所以 `case_inventory.main()` 返回 0)。

### 7.1 `documentWarnings = 1` 解释

inventory 多报了一个 `documentWarnings = 1` 字段(用户期望列表中未列这个指标,这里如实记录它在 strict-mode 下不影响通过)。

### 7.2 17 章节覆盖

主章节 group by:

```text
UA-1-1 = 12 / UA-1-2 = 8 / UA-1-3 = 8 / UA-1-4 = 6
UA-1-5 = 9 / UA-1-6 = 13
UA-2-1 = 112 / UA-2-2 = 67 / UA-2-3 = 32 / UA-2-4 = 27 / UA-2-5 = 27
UA-3-1 = 20 / UA-3-2 = 21 / UA-3-3 = 22 / UA-3-4 = 8 / UA-3-5 = 12 / UA-3-6 = 15
```

合计 **419** ✓。

## 8. 完整错误堆栈

本报告只产出 1 个真实异常(脚本 step3 的 catalog-export stdout):

```text
$ python -m ua_test_harness catalog --output ...
D:\Python311\python.exe: No module named ua_test_harness.__main__; 'ua_test_harness' is a package and cannot be directly executed
```

(`catalog.stderr.log` 完整内容)

类型:`ModuleNotFoundError` 转 `SystemExit` 1 —— 框架 typo bug:

| 项 | 值 |
|---|---|
| 触发位置 | `scripts/run_all_case_static.ps1:60`:`-Arguments @("-m", "ua_test_harness", "catalog", "--output", $catalogPath)` |
| 实际有效命令 | `python -m ua_test_harness catalog ...` |
| Python 解释器错误 | `No module named ua_test_harness.__main__; 'ua_test_harness' is a package and cannot be directly executed` |
| 根因 | `ua_test_harness` 是 package 而非 standalone module;CLI 必须用 `python -m ua_test_harness.cli catalog ...` 形式 |
| 修复方向(按用户纪律不改)| 应改 `run_all_case_static.ps1:60` 的 ArgumentList 第 2 / 3 项,把 `"ua_test_harness"` 与 `"catalog"` 之间插入 `"cli"` |
| 本报告处理 | **不修**。改用 `python -m ua_test_harness.cli catalog ...` 独立手工跑出主产物,数据落地在 §4 §7 章节 |

## 9. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **framework typo bug**(step3)| `python -m ua_test_harness catalog ...` → `ModuleNotFoundError: No module named ua_test_harness.__main__` | `run_all_case_static.ps1` 用 `python -m ua_test_harness catalog` 而非 `python -m ua_test_harness.cli catalog` | **不修**(用户禁改 scripts)|
| **framework 测试结果** | pytest 46 passed / 0 collection error / 0 SyntaxError | 已修:commit 51a9f57 后,`type_mapping.normalize_opcua_type_name` 已暴露,`test_type_mapping.py` 可正常 import | 真 |
| **inventory schema 缺口** | inventory 不暴露 `cases[].assertions` 字段 | `ua_test_harness/case_inventory.py:_case_from_cells` 没把 `expected` 拆成 `assertions` | **不修**(用户禁改);以 catalog 主产物为准 |
| **inventory `documentWarnings=1`** | strict-mode 通过,但报 1 个 document warning | inventory 内部统计字段,非结构性失败 | 真 |

## 10. 数据完整性交叉验证

| 验证维度 | 来源 | 结果 |
|---|---|---|
| pytest ua_test_harness/unit_tests | run_all_case_static.ps1 step2 | `46 passed in 4.24s` |
| compileall ua_test_harness tpt_api | 脚本 step1 | exit 0 |
| catalog chapters | `python -m ua_test_harness.cli catalog`(独立)| 17 chapters |
| catalog total cases | 独立 catalog.json | **419** |
| catalog 唯一 ID 数 | 独立 catalog.json | 419(unique = total)|
| inventory documented | 独立 case_inventory.json | **419** |
| inventory implemented | 独立 case_inventory.json | **419** |
| inventory malformed / duplicates / orphans | 同上 | **0 / 0 / 0** |
| inventory structureOk | 同上 | **true** |
| 每 case 都有 steps | catalog.json 全部 419 cases | 419 / 419(steps 长度 1~7)|
| 每 case 都有 assertions | catalog.json 全部 419 cases.assertions 数组 | **419 / 419**(都恰好 1 个 assertion)|

## 11. 总结

| 用户要求 | 实测 | 评 |
|---|---|---|
| 1. Python 编译通过 | **YES** | exit 0 |
| 2. 单元测试全部通过 | **YES** | 46 / 46 passed |
| 3. 无 import / collection / SyntaxError | **YES** | 0 错误 |
| 4. catalog Case 总数 = 419 | **YES** | 419(脚本自身 step3 中断,但独立手工命令给出 419)|
| 5. Case ID 全部唯一 | **YES** | 419 / 419 unique |
| 6. 每 case 都有 steps 和 assertions | **YES** | steps 长 1~7 / assertions 都是 1 个 |
| 7a. documented = 419 | **YES** | 419 |
| 7b. implemented = 419 | **YES** | 419 |
| 7c. unimplemented = 0 | **YES** | 0 |
| 7d. malformed = 0 | **YES** | 0 |
| 7e. duplicates = 0 | **YES** | 0 |
| 7f. orphans = 0 | **YES** | 0 |
| 7g. structureOk = true | **YES** | true(strict-structure 通过)|
| 8. 完整异常堆栈 | 见 §8 | 1 个 framework typo bug(`-m ua_test_harness catalog`),真实记录 |
| **静态验证整体**| **PASS**(数据层)| 用户脚本本身 exit 1 因 framework typo bug;真实 catalogue + inventory 全部 PASS |

报告完成时间:2026-07-12 13:31。
