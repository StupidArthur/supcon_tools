# stage3-validation-51a9f57.md — 在 HEAD 3f8dce3 上 Stage 3 真实数据流验证(2026-07-12 13:42)

## 0. 目标 HEAD

```text
3f8dce349ca3f6e557e890c6d30c0afa77a5c209
```

(本报告基于真实 commit 跑出的数据;前一份 commit `51a9f57 fix(automation): complete OPC UA type mapping api` 引入 type_mapping 修复;本次 HEAD 相对它再前进,新增 `dataflow_probe_entry.py` 在调用 `dataflow_probe.main()` 前 monkey-patch `tpt_api.types.DataTypes` 加入 OPC UA 类型别名,使得 `DataTypes["INT32"]` 取得到 6。)

## 1. 退出码与产物

```text
stage3 exit code: 1
```

`scripts/run_automation_stage3.ps1` 在 step 3 (`tpt-dataflow-probe`) **FAIL**(Python `dataflow_probe.py` 90s 内没读到 RT 值,`TimeoutError: first RT value timeout after 90.0s; last=None`)。

### 1.1 产物目录

```
F:\github\supcon_tools\output\automation_stage3_20260712_134153
```

| 文件 | 大小 | 来源 |
|---|---|---|
| `dataflow-probe.json` | 4 280 | step3(json 主产物)|
| `dataflow-probe.log` | 4 278 | step3(stdout tee)|
| `dataflow-probe.stderr.log` | 0 | step3(stderr)|
| `mock-probe.json` | 1 224 | step2(json 主产物)|
| `mock-probe.log` | 1 226 | step2(stdout tee)|
| `mock-probe.stderr.log` | 0 | step2(stderr)|
| `mock.stderr.log` | 0 | mock 子进程 stderr |
| `mock.stdout.log` | 0 | mock 子进程 stdout |
| `pytest.log` | 204 | step1(unit_tests)|
| `stage3-result.json` | 1 314 | 脚本主产物 |
| `transcript.log` | 6 602 | PowerShell Start-Transcript |
| `ua_mocker_20260711.log` | 15 353 454 | finally 复制(历史)|
| `ua_mocker_20260712.log` | 6 181 487 | finally 复制 |

> **本次 stage3 走到了 step 3**(前几次因 framework typo 或 unit-tests collection error 在 step 1 即中断;这次前两步全 PASS,真正进入 TPT 真实数据流)。

## 2. `stage3-result.json` 完整

```json
{
    "schemaVersion": 1,
    "generatedAt": "2026-07-12T13:43:35.2918870+08:00",
    "repoRoot": "F:\\github\\supcon_tools",
    "baseUrl": "http://10.10.58.153:31501/",
    "username": "admin",
    "tenantId": "",
    "localIp": "10.30.70.77",
    "mockPort": 18964,
    "passwordPresent": true,
    "steps": [
        { "name": "unit-tests",          "status": "PASS", "startedAt": "2026-07-12T13:41:53.9991970+08:00", "finishedAt": "2026-07-12T13:41:57.4135681+08:00" },
        { "name": "local-mock-probe",    "status": "PASS", "startedAt": "2026-07-12T13:41:59.4832468+08:00", "finishedAt": "2026-07-12T13:42:02.5388585+08:00" },
        { "name": "tpt-dataflow-probe",  "status": "FAIL",
          "startedAt": "2026-07-12T13:42:02.5398569+08:00", "finishedAt": "2026-07-12T13:43:35.2225525+08:00",
          "error": "exit code 1" }
    ],
    "fatalError": "exit code 1",
    "status": "FAIL"
}
```

## 3. Step by Step

### 3.1 Step 1: `unit-tests`

| 维度 | 实测 |
|---|---|
| status | **PASS** |
| 退出码 | 0(`internal pytest` 在脚本内 ExitCode 模式未传)|

`pytest.log`(完整):

```text
..................................                                       [100%]
34 passed in 2.55s
```

无 collection error / 无 SyntaxError / 无 ImportError。

### 3.2 Step 2: `local-mock-probe`(`opc.tcp://127.0.0.1:18964/ua_mocker/`)

| check | 结果 |
|---|---|
| `browse_mocker_root` | PASS(`mocker` 父节点)|
| `browse_mocker_children` | PASS(`count=1` : `mocker_0`,阈值 ≥1)|
| `read_static` | PASS(`smoke_static_1 = 12.5` vs `expected=12.5`)|
| `write_readback` | PASS(写 42.25,回读 42.25)|
| `changing_value` | PASS(`smoke_change_1` 在 1.2s 内由 2 → 4)|
| `ok`(整体)| **true** |
| `elapsedMs` | 1234.0 |

`mock-port = 18964`(从 `run_automation_stage3.ps1` 接收 `-MockPort 18964`)。

### 3.3 Step 3: `tpt-dataflow-probe`

`dataflow-probe.json` 完整摘要:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T05:42:03.077564Z",
  "baseUrl": "http://10.10.58.153:31501/",
  "mockPort": 18964,
  "datasource": {
    "name": "ua_auto_flow_20260712_134203",
    "endpoint": "opc.tcp://10.30.70.77:18964/ua_mocker/"
  },
  "tag": {
    "name": "ua_auto_flow_tag_20260712_134203",
    "baseName": "smoke_change_1"
  },
  "checks": [
    { "name": "login",             "ok": true },
    { "name": "create_datasource", "ok": true, "dsId": 50,
      "response": {
        "id": 50, "createTime": "2026-07-12 13:42:44", "updateTime": "2026-07-12 13:42:44",
        "createBy": "admin", "updateBy": "admin",
        "dsName": "ua_auto_flow_20260712_134203", "dsType": 1, "dsSubType": 4,
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/", "dsExtInfo": {}
      } },
    { "name": "datasource_alive",  "ok": true,
      "datasource": {
        "id": 50, "name": "ua_auto_flow_20260712_134203", "dsName": "ua_auto_flow_20260712_134203",
        "dsType": 1, "dsTypeDesc": "Real time database",
        "dsSubType": 4, "dsSubTypeDesc": "OPC-UA-Server",
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/",
        "supportSub": true, "dsExtInfo": {}, "dsStatus": 1, "alive": true
      } },
    { "name": "create_tag",        "ok": true, "tagId": 14133,
      "response": {
        "id": 14133, "createTime": "2026-07-12 13:42:45", "updateTime": "2026-07-12 13:42:45",
        "tagName": "ua_auto_flow_tag_20260712_134203",
        "tagBaseName": "smoke_change_1",
        "tagDesc": "Stage 3 minimal dataflow probe",
        "tagType": 1, "dsId": 50, "unit": "",
        "dataType": 6, "baseDataType": 6,
        "createBy": "admin", "updateBy": "admin",
        "onlyRead": true, "cacheNum": 0, "frequency": 1,
        "isVector": true, "needPush": true
      } },
    { "name": "query_tag",         "ok": true,
      "tag": {
        "id": 14133, "name": "ua_auto_flow_tag_20260712_134203",
        "tagName": "ua_auto_flow_tag_20260712_134203", "tagBaseName": "smoke_change_1",
        "tagType": 1, "tagTypeName": "一次位号",
        "dsId": 50, "dsName": "ua_auto_flow_20260712_134203",
        "dataType": 6, "dataTypeName": "INT",
        "avgRelatedTagName": "", "onlyRead": true, "frequency": 1,
        "isVector": true, "needPush": true
      } },
    { "name": "probe_exception",   "ok": false,
      "error": "TimeoutError: first RT value timeout after 90.0s; last=None",
      "traceback": "Traceback (most recent call last):\n  File \"F:\\github\\supcon_tools\\ua_test_harness\\dataflow_probe.py\", line 165, in probe\n    first_rt = _wait(\"first RT value\", fetch_rt, timeout=timeout)\n               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"F:\\github\\supcon_tools\\ua_test_harness\\dataflow_probe.py\", line 34, in _wait\n    raise TimeoutError(f\"{name} timeout after {timeout}s; last={last!r}\")\nTimeoutError: first RT value timeout after 90.0s; last=None\n" }
  ],
  "cleanup": [
    { "name": "delete_tag",        "ok": true, "tagId": 14133 },
    { "name": "delete_datasource", "ok": true, "dsId": 50 },
    { "name": "verify_cleanup",    "ok": true,
      "datasourceRemaining": [], "tagRemaining": [] }
  ],
  "elapsedMs": 91172.0,
  "ok": false
}
```

## 4. 数据源是否达到 alive=true?

**是**。`datasource_alive` 检查返回 `alive: true`:

| 字段 | 值 |
|---|---|
| 数据源 ID(dsId)| **50** |
| 数据源名 | `ua_auto_flow_20260712_134203` |
| endpoint | `opc.tcp://10.30.70.77:18964/ua_mocker/` |
| `dsType / dsSubType` | `1 / 4` |
| `dsStatus` | `1`(启用)|
| **`alive` 检查** | **`true`** |
| `createTime` | `2026-07-12 13:42:44` |
| `supportSub` | `true` |

TPT 实际上在 13:42:44 ~ 13:42:45 之间对 `0.0.0.0:18964` 完成了 subsystem 检测 / 建立订阅(在 mock 的 `ua_mocker_20260712.log` 中可看到 `New connection from ('10.10.58.153', ...)` 后 `create subscription request`)。

## 5. 位号是否创建成功?

**是**。`create_tag` 返回 `tagId=14133`,完整响应里有 `tagBaseName=smoke_change_1 / dataType=6(INT) / tagType=1(一次位号) / dsId=50 / frequency=1 / onlyRead=true / isVector=true / needPush=true`。

`query_tag` 也确认位号存在,与 create_tag 响应字段一致(只是多 `tagTypeName` / `dataTypeName` 等描述字段)。

| 字段 | 值 |
|---|---|
| `tagName` | `ua_auto_flow_tag_20260712_134203` |
| `tagBaseName` | `smoke_change_1` |
| `dataType / dataTypeName` | `6 / INT` |
| `tagType / tagTypeName` | `1 / 一次位号` |
| `dsId / dsName` | `50 / ua_auto_flow_20260712_134203` |
| `frequency` | `1` |
| `onlyRead` | `true` |
| `isVector` | `true` |
| `needPush` | `true` |
| `unit` | `""` |
| `createBy` | `admin` |

## 6. 两次实时值 / quality / timestamp

### 6.1 第一次实时值

**未读到**。

```text
TimeoutError: first RT value timeout after 90.0s; last=None
```

`probe()` 用 `_wait("first RT value", fetch_rt, timeout=timeout)`(timeout=90s),`fetch_rt` 调 `get_rt_value(api, [tag_name], is_from_db=False)`,等 90 秒 **`last=None`** —— 也就是 90 秒连续 `fetch_rt()` 都返回 `None`(没拿到带 quality 非空的 RT 数据)。

### 6.2 第二次实时值是否变化

**未读到**(因 first 已 timeout)。

## 7. 位号和数据源清理是否成功?

**位号**:**PASS**(cleanup `delete_tag` 成功 `tagId=14133`)

**数据源**:**PASS**(cleanup `delete_datasource` 成功 `dsId=50`)

**复核**:**PASS**(`verify_cleanup` 给出 `datasourceRemaining: []` / `tagRemaining: []`)

## 8. `ua_auto_flow_*` 残留

**否**(残留数 = 0)。

| 位置 | 残留数 |
|---|---|
| TPT `ds-info` active(`list_ds_info filter dsName=ua_auto_flow_`)| **0** |
| TPT `tag-info` active(`list_tags filter tagName=ua_auto_flow_`)| **0** |
| TPT recycle bin(`list_recycle_tags` 过滤 `ua_auto_flow_*`)| **0** |
| `dataflow-probe.json` 自带 `verify_cleanup` | `datasourceRemaining: []` / `tagRemaining: []` |

四路相互验证 → **真正零残留**。

## 9. 完整异常堆栈

本轮只产生 1 个真实异常(`dataflow_probe.py` 内的 `_wait` timeout):

```text
Traceback (most recent call last):
  File "F:\github\supcon_tools\ua_test_harness\dataflow_probe.py", line 165, in probe
    first_rt = _wait("first RT value", fetch_rt, timeout=timeout)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "F:\github\supcon_tools\ua_test_harness\dataflow_probe.py", line 34, in _wait
    raise TimeoutError(f"{name} timeout after {timeout}s; last={last!r}")
TimeoutError: first RT value timeout after 90.0s; last=None
```

类型:`TimeoutError`(运行期真实失败,非 framework typo)。

### 9.1 对照前几轮的"真实`KeyError 'INT32'`" 

前几次报告里反复出现的 `KeyError: 'INT32'`(由 `dataflow_probe.py:127 DataTypes["INT32"]` 触发)在本次**已不存在** —— main 已经合入:

1. `type_mapping.py` 暴露 `normalize_opcua_type_name`(`fix(automation): complete OPC UA type mapping api`);
2. 新增 `dataflow_probe_entry.py`,**运行期**为 `tpt_api.types.DataTypes` monkey-patch 加入 OPC UA 类型兼容别名(把 `INT32=6` 这种 OPC UA 命名注入 dict)。

本次直接调用的 `dataflow_probe.py:127` 仍写 `DataTypes["INT32"]`,但脚本改走 `dataflow_probe_entry`,所以取得到 6。**这意味着框架依赖运行期 monkey-patch** —— 不修源码,只是入口侧注入。

## 10. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **运行期真实 timeout** | `first RT value timeout after 90.0s` | TPT 数据采集引擎建立订阅后,**90 秒内 `get_rt_value` 没拿到带 quality 的 RT 条目**;`fetch_rt()` 返回 `last=None` 持续 | **不修**;按用户纪律保留真实结果 |
| **可能因素 A:ua_mocker 多 group 缺失** | browse_mocker_children 仍只见到 `mocker_0`(无 `mocker_1`)| ua_mocker 在 Windows + asyncua 配置下,smoke_stage3.yaml 有 2 个 group 但只建出 1 个 group 父节点;位号 `smoke_change_1` 在 ns=2 下是 String NodeId,不挂在 `mocker_*` 之下,所以 browse 看不全不影响直接读。但**TPT 数据采集引擎读 OPC UA 需要先 browse 找到节点**再订阅,browse 不全可能订阅失败或只能收到一部分 | 第三方 |
| **可能因素 B:mock 与 TPT 数据采集延迟** | 13:42:45 创 tag,13:43:35 fail——90s 内 RT 都没起来 | tag 创后通常要 5~10s 才会被采集到;也可能 TPT 端订阅的 OPC UA 地址 / 节点 ID 形式与 ua_mocker 的实际命名空间不一致(tagBaseName 字段在这个 mock 上未走 NS 限定?) | 待研究 |
| **framework bug 已修对照**| 之前的 `DataTypes["INT32"] KeyError` / `test_type_mapping.py import normalize_opcua_type_name` 都已修 | 见 §9.1 | 已合入 main |
| **是否触发了 framework 修复后尚未触及的角落** | 需后续 PR 关注 | — | 留 PR |

## 11. 总结

| 用户要求 | 实测 | 评 |
|---|---|---|
| 1. 单元测试通过 | **YES**(34 passed)|
| 2. Mock probe 通过 | **YES**(5/5,1234ms)|
| 3. 数据源 alive=true | **YES**(`dsId=50`, `alive:true`)|
| 4. 位号创建成功 | **YES**(`tagId=14133`, `dataType=INT / tagBaseName=smoke_change_1`)|
| 5. 第一次实时值 | **未读到**(90s timeout)|
| 6. 第二次实时值是否变化 | **未读到** |
| 7. 位号 / 数据源清理 | **位号 PASS / 数据源 PASS / verify PASS** |
| 8. `ua_auto_flow_*` 残留 | **0**(4 路核查一致)|
| 9. 完整异常堆栈 | 见 §9 |
| 整体 stage3 退出码 | **1** |

按工程纪律 + 用户规则:
- 本轮**未改动 framework / scripts / case / fixture / mock / 断言 / 测试文档**;
- 仅**读取 / 运行**脚本,真实记录每一步状态;
- 静态脚本 4 步全 PASS(framework typo bug 已修);
- Stage 3 真正推进到 `create_tag`(通过 monkey-patch 解决 KeyError)、`query_tag`(PASS),`get_rt_value` 90s 不出 RT(运行期 timeout,真实环境状态如实记录,符合"不绕路不吞错"纪律)。

报告完成时间:2026-07-12 13:42。
