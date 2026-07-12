# stage3-validation-51a9f57.md — 在 commit 51a9f57 上独立 Stage 3 验证报告

## 0. 目标 commit 与执行方法

按用户要求本报告固定在 commit:

```text
51a9f57 fix(automation): complete OPC UA type mapping api
```

(仓库历史:`51a9f57 ← 4838c36 ← 42a75a1`(本报告 `42a75a1` 已基于 main 提交 + 用户 fix 后 main 含 `51a9f57`))

> **如实记录执行方法(用户要求脚本到位,实际只跑了 step1)**:
> `run_automation_stage3.ps1` 在本 commit 上**只跑完 step 1 `unit-tests`** 就因 pytest collection error 终止,后续 step 2 / step 3(`local-mock-probe` / `tpt-dataflow-probe`)**未被脚本触发**。
> 报告 §3 的 mock-probe 与 §5 的 dataflow-probe 是本报告撰写方**手动调用**与脚本 step 2 / step 3 的**等价步骤**(独立启动 `ua_mocker/smoke_stage3.yaml` + 调 `python -m ua_test_harness.mock_probe` + 调 `python -m ua_test_harness.dataflow_probe`),**未改 framework / mock / tpt_api / case / 断言**。
> 这不是测试框架问题:framework 自身有 typo bug,pytest collection 阶段就崩,Run-Step 错误捕获后 throw 让后续 step 终止。

## 1. 退出码与产物清单

```text
stage3 exit code: 1
```

### 1.1 脚本产物目录

```
F:\github\supcon_tools\output\automation_stage3_20260712_124011
```

| 文件 | 大小 | 来源 |
|---|---|---|
| `pytest.log` | 2 116 | step1(unit-tests)|
| `stage3-result.json` | 742 | 脚本主产物 |
| `transcript.log` | 2 050 | PowerShell Start-Transcript |
| `ua_mocker_20260711.log` | 14 673 894 | finally 复制(历史)|
| `ua_mocker_20260712.log` | 5 389 992 | finally 复制(脚本未启动 mock)|

> **未生成** `mock-probe.{json,log,stderr.log}`、`dataflow-probe.{json,log,stderr.log}`、`mock.{stdout,stderr}.log`(因为脚本 step2/step3 未触发)。它们在 §3 / §5 中通过手工等价步骤生成到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\`(不会提交)。

### 1.2 `stage3-result.json`

```json
{
    "schemaVersion": 1,
    "generatedAt": "2026-07-12T12:40:58.4810999+08:00",
    "repoRoot": "F:\\github\\supcon_tools",
    "baseUrl": "http://10.10.58.153:31501/",
    "username": "admin",
    "tenantId": "",
    "localIp": "10.30.70.77",
    "mockPort": 18964,
    "passwordPresent": true,
    "steps": [
        {
            "name": "unit-tests",
            "status": "FAIL",
            "startedAt": "2026-07-12T12:40:56.3922897+08:00",
            "finishedAt": "2026-07-12T12:40:58.4438640+08:00",
            "error": "exit code 2"
        }
    ],
    "fatalError": "exit code 2",
    "status": "FAIL"
}
```

## 2. Python 单元测试是否通过?

**否**(`FAIL` exit 2)。

**framework bug 详情**(完整堆栈):

```text
ImportError while importing test module 'F:\github\supcon_tools\ua_test_harness\unit_tests\test_type_mapping.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\Python311\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ua_test_harness\unit_tests\test_type_mapping.py:5: in <module>
    from ua_test_harness.type_mapping import (
E   ImportError: cannot import name 'normalize_opcua_type_name' from 'ua_test_harness.type_mapping'
    (F:\github\supcon_tools\ua_test_harness\type_mapping.py)
=========================== short test summary info ============================
ERROR ua_test_harness/unit_tests/test_type_mapping.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.19s
```

类型:`ImportError`(framework 自身 typo bug — `test_type_mapping.py:5` 期望 import `normalize_opcua_type_name`,但 `ua_test_harness/type_mapping.py:30` 只暴露 `tpt_data_type_key` 与 `tpt_data_type_value`,没有 `normalize_opcua_type_name`)。按用户「不修 framework」纪律,保留真实错误。

## 3. Mock probe 是否通过?

**是**。

手工启动 `ua_mocker/smoke_stage3.yaml`(端口 18964),然后调 `python -m ua_test_harness.mock_probe --endpoint "opc.tcp://127.0.0.1:18964/ua_mocker/"`(写盘到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\mock-probe.json`):

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T04:41:00.005743Z",
  "endpoint": "opc.tcp://127.0.0.1:18964/ua_mocker/",
  "namespaceIndex": 2,
  "checks": [
    { "name": "browse_mocker_root",    "ok": true,
      "objectChildren": ["QualifiedName(NamespaceIndex=0, Name='Locations')",
                         "QualifiedName(NamespaceIndex=0, Name='Server')",
                         "QualifiedName(NamespaceIndex=0, Name='Aliases')",
                         "QualifiedName(NamespaceIndex=2, Name='mocker')"] },
    { "name": "browse_mocker_children","ok": true, "count": 1,
      "children": ["QualifiedName(NamespaceIndex=2, Name='mocker_0')"] },
    { "name": "read_static",           "ok": true, "nodeId": "ns=2;s=smoke_static_1",
      "actual": 12.5,  "expected": 12.5 },
    { "name": "write_readback",        "ok": true, "nodeId": "ns=2;s=smoke_static_1",
      "actual": 42.25, "expected": 42.25 },
    { "name": "changing_value",        "ok": true, "nodeId": "ns=2;s=smoke_change_1",
      "before": 4, "after": 6, "waitSec": 1.2 }
  ],
  "elapsedMs": 1234.0,
  "ok": true
}
```

| step | 结果 |
|---|---|
| browse_mocker_root | **PASS**(找到 `mocker` 父节点)|
| browse_mocker_children | **PASS**(`count=1`,阈值 ≥1)|
| read_static | **PASS**(`smoke_static_1 = 12.5`)|
| write_readback | **PASS**(写 42.25 / 回读 42.25)|
| changing_value | **PASS**(`smoke_change_1` 在 1.2s 内由 4 → 6)|
| `ok` overall | **true** |
| Elapsed | 1234 ms |

## 4. 数据源是否创建并达到 `alive=true`?

**是**。

手工调 `python -m ua_test_harness.dataflow_probe --base-url http://10.10.58.153:31501/ --username admin --local-ip 10.30.70.77 --mock-port 18964 --timeout 90`,写盘到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\dataflow-probe.json`:

| 字段 | 值 |
|---|---|
| 数据源 ID(dsId)| **49** |
| 数据源名 | `ua_auto_flow_20260712_124101` |
| endpoint | `opc.tcp://10.30.70.77:18964/ua_mocker/` |
| `dsType / dsSubType` | `1 / 4`(`REAL_TIME_DB / OPC_UA_SERVER`)|
| `createTime / updateTime` | `2026-07-12 12:41:43` |
| `dsStatus` | `1`(启用)|
| **`alive` (datasource_alive 检查)** | **`true`** |

`dataflow-probe.json` 关键节选:

```json
{
  "checks": [
    { "name": "login",             "ok": true },
    { "name": "create_datasource", "ok": true, "dsId": 49,
      "response": {
        "id": 49,
        "dsName": "ua_auto_flow_20260712_124101",
        "dsType": 1, "dsSubType": 4,
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/"
      } },
    { "name": "datasource_alive",  "ok": true,
      "datasource": {
        "id": 49,
        "name": "ua_auto_flow_20260712_124101",
        "dsName": "ua_auto_flow_20260712_124101",
        "dsType": 1, "dsTypeDesc": "Real time database",
        "dsSubType": 4, "dsSubTypeDesc": "OPC-UA-Server",
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/",
        "supportSub": true,
        "dsStatus": 1, "alive": true
      } },
    ...
  ]
}
```

## 5. 位号是否创建成功?

**否**(framework typo bug 与上一轮 stage3-agent-report 一致)。

**`dataflow_probe.py:127`**

```python
data_type=DataTypes["INT32"],
```

`KeyError: 'INT32'`,因为 `tpt_api.types.DataTypes` dict 在 `tpt_api/python/tpt_api/types.py:120` 的 key 是 `"INT"=6`,**没有** `"INT32"` key(平台的 enum 没有 INT32,只有 INT/LONG/FLOAT/DOUBLE 等)。
commit `51a9f57` 没有修复这个 KeyError,**也**没新增 `INT32` 别名。

所以此 commit 状态下:
- `add_tag` 实际**未发出**(异常发生在 `add_tag(...)` 求值参数时,`DataTypes["INT32"]` 在参数 binding 阶段抛 KeyError)
- `tag_id` 仍为 `None`,后续步骤全部跳过
- `cleanup.delete_tag` 因 `tag_id` 为空跳过

`dataflow-probe.json` checks 节选:

```json
{
  "checks": [
    ...
    { "name": "probe_exception", "ok": false,
      "error": "KeyError: 'INT32'",
      "traceback": "Traceback (most recent call last):\n  File \"F:\\github\\supcon_tools\\ua_test_harness\\dataflow_probe.py\", line 127, in probe\n    data_type=DataTypes[\"INT32\"],\n              ~~~~~~~~~^^^^^^^^^\nKeyError: 'INT32'\n" }
  ]
}
```

### 5.1 位号 ID / `tagBaseName` / 数据类型 / 查询

| 字段 | 实测 |
|---|---|
| **位号 ID** | **未创建**(create_tag 步抛 KeyError,TPT 中无此条)|
| **tagName**(若要)| 试图命名为 `ua_auto_flow_tag_20260712_124101`,未发到 TPT |
| **`tagBaseName`** | 试图写入 `smoke_change_1`,因 create_tag 未发,无字段 |
| **数据类型** | 试图 `DataTypes["INT32"]` → **抛 KeyError**(平台 enum 不含 INT32)|
| **查询结果** | `list_tags(data={"tagName": ua_auto_flow_tag_20260712_124101})` **未执行**(无 tag 要查)|

## 6. 第一次实时值 / quality / timestamp

**未读到**(`read_rt_first` 未执行)。

原因:依赖 `create_tag` 成功,实际 create_tag 在 `data_type=DataTypes["INT32"]` 求值阶段抛 KeyError,异常被 `dataflow_probe.py:178 except` 捕获后写入 `probe_exception`;`_wait("first RT value", fetch_rt, ...)` 步之前的 `tag_row = _wait("tag present", fetch_tag, timeout=30.0)` 也因 tag 未创建而**未到这一步**(异常先抛,不会执行 fetch_tag)。

## 7. 第二次实时值是否变化

**未读到**(`read_rt_changed` 未执行)。

原因同 §6 —— 整个 RT 值读取从未发起。

## 8. 位号和数据源清理是否成功?

| 步骤 | 结果 |
|---|---|
| `delete_tag`(tag_id=49)| **未执行**(`tag_id` 仍为 None;`if api is not None and tag_id:` 跳过)|✓ 无残留可清 |
| `delete_datasource dsId=49` | **PASS**(`cleanup_add("delete_datasource", True, dsId=49)`)|
| `verify_cleanup`(残留核查)| **PASS**(`datasourceRemaining: [], tagRemaining: []`)|

`dataflow-probe.json` cleanup 节选:

```json
"cleanup": [
  { "name": "delete_datasource", "ok": true, "dsId": 49 },
  { "name": "verify_cleanup",    "ok": true,
    "datasourceRemaining": [], "tagRemaining": [] }
]
```

**注意 cleanup 阶段没看到 `delete_tag` 条目** — 因为 tag 没建,`tag_id` 也没创建,`finally` 块 `if api is not None and tag_id:` 表达式短路跳过。这是 **正常行为**(无需清理不存在的东西),不是 cleanup bug。

## 9. 是否存在 `ua_auto_flow_*` 残留?

**否**(`dataflow_probe` 自带 `verify_cleanup` 给出 `datasourceRemaining: [] / tagRemaining: []`)。

为了独立交叉验证,我同时直接调 `tpt_api` 做全量扫描(在 `C:\Users\yuzechao\AppData\Local\Temp\opencode\stage3_residual_51a9f57.txt` 留有脚本输出):

```text
=== DS ua_auto_flow_* === 0
=== TAG ua_auto_flow_* (active) === 0
=== TAG ua_auto_flow_* (recycle) === 0
```

三次相互验证:`dataflow_probe.verify_cleanup` (internal) + 独立 `list_ds_info` + 独立 `list_tags` + 独立 `list_recycle_tags` → **残留数 = 0**。

## 10. 完整异常堆栈

本 commit 运行期间只产生 **1 个真实异常**:

```text
Traceback (most recent call last):
  File "F:\github\supcon_tools\ua_test_harness\dataflow_probe.py", line 127, in probe
    data_type=DataTypes["INT32"],
              ~~~~~~~~~^^^^^^^^^
KeyError: 'INT32'
```

类型:`KeyError`(framework typo bug,此 commit 未修)。

`dataflow_probe.py` 在 line 178 有 `except Exception as exc` 把异常捕获后写入 `result["checks"][-1] = {name:"probe_exception", ok:false, ...}`,**未向上抛**。所以脚本 step 看到的 `probe_exception` 项 + cleanup 块继续工作。

`stage3-result.json.fatalError` 是 `"exit code 2"` 而非 KeyError 详情 —— 因 step1 `unit-tests` 先失败(fatal 提前),`python -m ua_test_harness.dataflow_probe` 也就**没机会被调用**。当手工等价调用时,内部异常已被 catch,所以 `dataflow-probe.json` 写出 OK,只是 `result["ok"]=False`(因为 probe_exception 项 `ok=false`),`main()` 返回非零。

## 11. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 本 commit 是否触及 |
|---|---|---|---|
| **framework typo bug** | `test_type_mapping.py` import `normalize_opcua_type_name` 失败 | `type_mapping.py` 没暴露该 symbol(只暴露 `tpt_data_type_key` / `tpt_data_type_value`)| 否,本 commit 没动 test_type_mapping |
| **framework typo bug** | `dataflow_probe.py:127 DataTypes["INT32"]` KeyError | `tpt_api.types.DataTypes` dict 不含 "INT32" key | 本 commit 在 type_mapping.py 加 `tpt_data_type_key`/`tpt_data_type_value` 两函数,新增 `_ = ..."UINT` 行补全,**但**没动 `dataflow_probe.py` 也**没**改 `tpt_api.types.DataTypes` 字典 |
| **ua_mocker**(第三方,延续)| browse_mocker_children 只见到 1 个 group (`mocker_0`) | ua_mocker multi-group 子节点创建不完整 | 第三方,本 commit 不碰 |
| **pytest collection error → step1 fail** | run_automation_stage3.ps1 只产出 5 个文件,未触发 step2 / step3 | framework typo bug 让 pytest 收集阶段就崩 | 真实状态 |
| **mock probe + dataflow probe 手工等价运行** | 报告 §3 / §5 数据来自独立手工调用 | step1 fail → step2/3 未触发 | 不修 framework 的前提下补充观测 |

## 12. 总结

| 项 | 结果 |
|---|---|
| 1. Python 单元测试 | **FAIL**(`ImportError: normalize_opcua_type_name` — framework typo bug 未修)|
| 2. Mock probe | **PASS**(5/5, elapsed 1234ms)|
| 3. 数据源 `alive=true` | **PASS**(`dsId=49`, `dsName=ua_auto_flow_20260712_124101`, `alive: true`)|
| 4. 位号创建成功 | **FAIL**(`KeyError: 'INT32'` 在 `dataflow_probe.py:127`)|
| 5. 第一次 RT / quality / timestamp | **未读到**(tag 未创建)|
| 6. 第二次 RT 发生变化 | **未读到** |
| 7. 位号和数据源清理 | 位号 = N/A(未建);数据源 = **PASS**(dsId=49 delete OK)|
| 8. `ua_auto_flow_*` 残留 | **0**(verify_cleanup + 独立 list_ds/list_tags/list_recycle 三处一致)|
| 9. 完整异常堆栈 | 1 个 `KeyError: 'INT32'`(见 §10);属于 framework typo bug |
| 整体 stage3 退出码 | **1**(fatalError = "exit code 2",从 unit-tests step1 fail 起)|

报告完成时间:2026-07-12 12:42。

附:运行结束后,已执行

```powershell
git checkout main
git pull --rebase origin main
```

切回 main(已含 51a9f57 fast-forward,见 `Updating 42a75a1..51a9f57 / Fast-forward`)。
