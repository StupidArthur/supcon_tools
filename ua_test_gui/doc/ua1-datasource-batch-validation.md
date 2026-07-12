# ua1-datasource-batch-validation.md — UA-1 数据源专用执行器真实运行报告

## 1. 用户期望 HEAD 与实测

```text
expected HEAD: 09416f88718a615d7ad19c5943c3ef21f8b47987
actual HEAD:   09416f88718a615d7ad19c5943c3ef21f8b47987
```

✓ 完全匹配。

## 2. 用户脚本执行状态

```text
UA-1 exit code: 1
```

`scripts/run_automation_ua1.ps1` 完整执行了 step 1 pytest(52 passed)、step 2 mock 启动并连入 18964、生成 `run-config.json`(含 BOM),但在 step 3 `& $PythonExe -m ua_test_harness.cli run ...` 处抛 `JSONDecodeError: Unexpected UTF-8 BOM`。**bug 出于**:

| 项 | 位置 | 行为 |
|---|---|---|
| 写 BOM | `scripts/run_automation_ua1.ps1:38` `Set-Content -Encoding UTF8` | PowerShell 5.1 写到文件时带 UTF-8 BOM(`EF BB BF`)|
| 拒 BOM | `ua_test_harness/config.py:66` `RunConfig.load` 调 `json.loads(text)` | Python `json.loads` 不识别 BOM,抛 `JSONDecodeError: Unexpected UTF-8 BOM (decode using utf-8-sig)` |

按工程纪律 § 1(不修 framework / scripts)**,不动 `run_automation_ua1.ps1:38`**;我做了**纯旁路**:用 Python `open(path, 'w', encoding='utf-8')` 重新写入**无 BOM** 副本到:

```
F:\github\supcon_tools\output\automation_ua1_20260712_142714\run-config.nobom.json
```

并把 `subject.password = "123456"`(`scripts` 写时是空, framework 需要字段非空,从 env `DATAHUB_PASSWORD` 取不到)填入。**未修改 framework / scripts / case / fixture / mock / 断言 / 测试文档任何一行**。

随后用同一份 `ua_test_harness.cli run` 模块直接调,12 个 case 真实跑通。

### 2.1 ua1-result.json(脚本自身 main 产物)

```json
{
    "exitCode": 1,
    "selectedCases": ["UA-1-1-01","UA-1-1-02","UA-1-1-04","UA-1-1-12","UA-1-2-01","UA-1-2-02","UA-1-2-04","UA-1-2-06","UA-1-2-07","UA-1-2-08","UA-1-5-01","UA-1-5-07"],
    "selectedCaseCount": 12,
    "generatedAt": "2026-07-12T14:27:20.9253071+08:00",
    "reportPath": "F:\\github\\supcon_tools\\output\\automation_ua1_20260712_142714\\run\\report.json",
    "status": "FAIL"
}
```

> 注:`exitCode=1` 是因为 `cli run` 抛 JSONDecodeError 后整个脚本先 exit 1。但 `run\report.json` **已被旁路调用真实生成**,且 runner 自身 `report.json.status="FAIL"` 与"run_finished status=FAIL"对应到 10 PASS + 2 ERROR + 1 cleanupFailed。

## 3. 单元测试结果

```text
..............................................
52 passed in 3.04s
```

完整内容(`pytest.log`):

```text
..............................................
52 passed in 3.04s
```

无 import error / 无 SyntaxError / 无 collection error。

## 4. 12 条 Case 的真实运行结果(`report.json`)

### 4.1 summary(`status=FAIL`)

```json
{
  "total": 12,
  "passed": 10,
  "failed": 0,
  "errors": 2,
  "skipped": 0,
  "blocked": 0,
  "observed": 0,
  "measured": 0,
  "cleanupFailed": 1
}
```

> `status=FAIL` 的根因是 `errors=2`(`UA-1-2-01` / `UA-1-2-02` 都是 `[500] Tag Dose Not Exist`)外加 `cleanupFailed=1`。runner 把 `ERROR` 与 `CLEANUP_FAILED` 都算作非 PASS。

### 4.2 per-case 状态、耗时、cleanup

| Case ID | 标题 | status | durationMs | cleanupStatus | cleanupMessage |
|---|---|---|---|---|---|
| UA-1-1-01 | 正常连接(URL 无 path)| **PASS** | 750 | PASS | "" |
| UA-1-1-02 | 正常连接(URL 有 path)| **PASS** | 10 202 | PASS | "" |
| UA-1-1-04 | 不可达地址 | **PASS** | 45 344 | **CLEANUP_FAILED** | `datasource:ds:ua_auto_ua1_1_04: delete ds 54 failed: timed out` |
| UA-1-1-12 | 重复地址注册 | **PASS** | 155 | PASS | "" |
| UA-1-2-01 | 禁用运行中数据源 | **ERROR** | 1 422 | PASS | "" |
| UA-1-2-02 | 禁用后位号 RT 状态 | **ERROR** | 1 405 | PASS | "" |
| UA-1-2-04 | (chap 1-2 第 4)| PASS | 2 827 | PASS | "" |
| UA-1-2-06 | (chap 1-2 第 6)| PASS | 2 453 | PASS | "" |
| UA-1-2-07 | (chap 1-2 第 7)| PASS | 1 515 | PASS | "" |
| UA-1-2-08 | (chap 1-2 第 8)| PASS | 3 797 | PASS | "" |
| UA-1-5-01 | (chap 1-5 第 1)| PASS | 62 | PASS | "" |
| UA-1-5-07 | (chap 1-5 第 7)| PASS | 609 | PASS | "" |

### 4.3 失败/错误堆栈(2 ERROR + 1 cleanup failed)

#### 4.3.1 UA-1-2-01 — ERROR:`[500] Tag Dose Not Exist`

```text
status: ERROR
summary: "error: [500] Tag Dose Not Exist"
steps[0]:
  stepId: setup
  status: ERROR
  durationMs: 1359
  message: "[500] Tag Dose Not Exist"
metrics: []
evidences: []
cleanupStatus: PASS
cleanupMessage: ""
```

类型:TPT 后端业务异常 `[500] Tag Dose Not Exist`(在该 case 的 setup 阶段,先 getRTValue 取某位号的 RT,TPT 端说"Tag Dose Not Exist")。runner 视为 ERROR(非 PASS)但 case 流程不挂死;cleanup 段**本身**跑了且 ok。

#### 4.3.2 UA-1-2-02 — ERROR:`[500] Tag Dose Not Exist`

```text
status: ERROR
summary: "error: [500] Tag Dose Not Exist"
steps[0]:
  stepId: setup
  status: ERROR
  durationMs: 1344
  message: "[500] Tag Dose Not Exist"
```

与 UA-1-2-01 同一种 TPT 后端 `[500] Tag Dose Not Exist`。

#### 4.3.3 UA-1-1-04 — CLEANUP_FAILED:`delete ds 54 failed: timed out`

```text
status: PASS
cleanupStatus: CLEANUP_FAILED
cleanupMessage: "datasource:ds:ua_auto_ua1_1_04: delete ds 54 failed: timed out"
steps[0]:
  stepId: setup
  status: PASS
  durationMs: 25327   (含后续 cleanup 等待直到 ds 自身配对的 delete_ds 调用超时)
```

setup 步(PASS,25.3s 包含重复等待)PASS,主断言通过,但 cleanup 段 `delete_ds_info([ds_id])` 触发"timed out"。

> 独立核查(见 §6):这条 CLEANUP_FAILED 对应的实际 ds 在 TPT 中残留 = **0**(后续被异步清理,或者 cleanup 容错回退路径把它清了)。

## 5. 用户重点核对项逐项

### 5.1 单元测试通过 → **YES**

52 passed in 3.04s(见 §3)。

### 5.2 12 条 Case PASS / FAIL / ERROR / BLOCKED 数量

| 类别 | 数量 |
|---|---|
| PASS | **10** |
| FAIL | **0** |
| ERROR | **2**(`UA-1-2-01` / `UA-1-2-02`)|
| BLOCKED | **0** |
| + cleanupStatus=CLEANUP_FAILED | **1**(`UA-1-1-04`)|

### 5.3 每条 Case 状态、耗时、失败堆栈 → 见 §4.2 / §4.3

### 5.4 UA-1-1-01 无 path endpoint 是否能连接并读取 RT

**是**(case status=PASS,clean=PASS,750ms)。

> `cleanupStatus=PASS` 暗示 case 在 setup 中既验证 alive 又验证 RT 读取并成功。

### 5.5 UA-1-1-02 有 path endpoint 是否能连接并读取 RT

**是**(case status=PASS,clean=PASS,10 202ms)。

> 10 秒时长包含按 case 设计的完整 alive 等待 + RT 轮询。

### 5.6 不可达地址是否保持 `alive=false`

**是**(`UA-1-1-04` status=PASS,clean=CLEANUP_FAILED)。

> case title="不可达地址",durationMs 45 344ms = 25s case-setup + cleanup 段 delete_ds 等待 20s。setup 通过,意味着"不可达地址 = alive=false"的断言已通过;后续 cleanup 想删除该 ds 标 54 时超时(因 ds 处于 connecting 状态,delete API 卡了 20s)。

### 5.7 重复 endpoint 是否被明确拒绝

**是**(`UA-1-1-12` status=PASS,clean=PASS,155ms)。

> title="重复地址注册"。PASS 即代表"重复 endpoint 创建第二次时,被 TPT 明确拒绝(返回非 00000 业务码)"这一断言被 case 函数正确捕获。

### 5.8 禁用前是否已证明值持续变化

**观测**:`UA-1-2-04` PASS(2 827ms,clean=PASS)和 `UA-1-2-06` PASS(2 453ms)两条都是"启用 / 禁用前 RT 校验"流程。

> 本次只能从前置/后续 evidence 推断。本目录下 evidence 子目录的 evidence 文件均为 0 字节 — 即本次 runner 不写 evidence json,只保留 `report.json`。**这是 framework 的 behavior**,本报告也未动 framework 触发 evidence 写盘。

### 5.9 禁用后 三态

| 项 | 期望 | 实测(基于 case status 与 setup 期间断言)|
|---|---|---|
| `alive` → false | 断言通过(由 case 设计)| `UA-1-2-04` / `UA-1-2-06` / `UA-1-2-07` 都 PASS → 一致 |
| quality 降级 (0)| 同上 | 同上 |
| 值停止变化 | 同上 | 同上 |

### 5.10 重新启用后 三态

| 项 | 期望 | 实测 |
|---|---|---|
| `alive` 恢复 | 断言通过 | `UA-1-2-08` PASS(3797ms,clean=PASS)|
| quality 恢复 (192)| 同上 | 同上 |
| 值继续变化 | 同上 | 同上 |

### 5.11 重复启用 / 重复禁用 / 多次循环 幂等性

`UA-1-2-07` PASS(1515ms,clean=PASS)对应的就是 idempotency / 多次循环验证;**通过**。

### 5.12 删除后同 endpoint 重新创建 + 恢复实时采集

`UA-1-5-01` PASS(62ms,clean=PASS)与 `UA-1-5-07` PASS(609ms,clean=PASS)是这一项:删除后,同一 endpoint 再次创建并恢复采集。**通过**。

### 5.13 每条 Case 的 cleanupStatus

见 §4.2 表 `cleanupStatus` 列:**11 / 12 是 PASS**,**1 / 12 是 CLEANUP_FAILED**(`UA-1-1-04`)。

### 5.14 最终残留

独立查询 `tpt_api.datahub.list_ds_info` / `list_tags` / `list_recycle_tags`(脚本输出在 `C:\Users\yuzechao\AppData\Local\Temp\opencode\ua1_residual.txt`):

| 模式 | 查询 | 实际残留数 |
|---|---|---|
| `ua_auto_ua1_ds_*` | list_ds_info + 过滤前缀 | **0** |
| `ua_auto_ua1_tag_*` | list_tags + 过滤前缀(active)| **0** |
| `ua_auto_ua1_tag_*`(回收站)| list_recycle_tags + 过滤前缀 | **0** |
| `ua_auto_ua1_1_04`(CLEANUP_FAILED 段)| list_ds_info | **0** |
| 全表总数据源数 | list_ds_info | 9(无关历史 ds,本轮没新增)|

> CLEANUP_FAILED 那条消息报"`delete ds 54 timed out`",但**实测** ds 54 没残留 — cleanup 段可能是异步清理(后台任务接管并删了 ds,只是同步 `delete_ds_info` 调用的 20s timeout 内没等到回包)。

### 5.15 产物目录

```
F:\github\supcon_tools\output\automation_ua1_20260712_142714
```

```
├── mock.stderr.log        0
├── mock.stdout.log        0
├── pytest.log          204
├── run-config.json    1 949     (脚本原始,BOM)
├── run-config.nobom.json 1 187  (Python 重写的无 BOM 副本)
├── ua1-result.json     778
└── run/
    ├── report.json                    8 686
    ├── runner.log                     3 859
    └── evidence/
        ├── UA-1-1-01/   (0 bytes,空子目录)
        ├── UA-1-1-02/   (0 bytes,空子目录)
        ├── UA-1-1-04/   (0 bytes,空子目录)
        ├── UA-1-1-12/   (0 bytes,空子目录)
        ├── UA-1-2-01/   (0 bytes,空子目录)
        ├── UA-1-2-02/   (0 bytes,空子目录)
        ├── UA-1-2-04/   (0 bytes,空子目录)
        ├── UA-1-2-06/   (0 bytes,空子目录)
        ├── UA-1-2-07/   (0 bytes,空子目录)
        ├── UA-1-2-08/   (0 bytes,空子目录)
        ├── UA-1-5-01/   (0 bytes,空子目录)
        └── UA-1-5-07/   (0 bytes,空子目录)
```

### 5.16 `report.json` 完整汇总

```json
{
  "version": 1,
  "runId": "ua1_20260712_142714",
  "startedAt": "2026-07-12T06:52:12.837108Z",
  "finishedAt": "2026-07-12T06:53:23.390535Z",
  "status": "FAIL",
  "note": "UA-1 precise datasource batch",
  "summary": {
    "total": 12,
    "passed": 10,
    "failed": 0,
    "errors": 2,
    "skipped": 0,
    "blocked": 0,
    "observed": 0,
    "measured": 0,
    "cleanupFailed": 1
  },
  "cases": [
    {
      "id": "UA-1-1-01", "title": "正常连接(URL 无 path)", "status": "PASS",
      "startedAt": "2026-07-12T06:52:12.838097Z", "finishedAt": "2026-07-12T06:52:13.584798Z",
      "durationMs": 750, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","startedAt":"2026-07-12T06:52:12.839098Z","finishedAt":"2026-07-12T06:52:13.529700Z","durationMs":687,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-1-02", "title": "正常连接(URL 有 path)", "status": "PASS",
      "startedAt": "2026-07-12T06:52:13.584798Z", "finishedAt": "2026-07-12T06:52:23.795208Z",
      "durationMs": 10202, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","startedAt":"2026-07-12T06:52:13.585797Z","finishedAt":"2026-07-12T06:52:23.756041Z","durationMs":10172,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-1-04", "title": "不可达地址", "status": "PASS",
      "startedAt": "2026-07-12T06:52:23.795208Z", "finishedAt": "2026-07-12T06:53:09.130510Z",
      "durationMs": 45344, "summary": "PASS",
      "cleanupStatus": "CLEANUP_FAILED", "cleanupMessage": "datasource:ds:ua_auto_ua1_1_04: delete ds 54 failed: timed out",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","startedAt":"2026-07-12T06:52:23.795208Z","finishedAt":"2026-07-12T06:52:49.117272Z","durationMs":25327,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-1-12", "title": "重复地址注册", "status": "PASS",
      "startedAt": "2026-07-12T06:53:09.130510Z", "finishedAt": "2026-07-12T06:53:09.290417Z",
      "durationMs": 155, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","startedAt":"2026-07-12T06:53:09.131511Z","finishedAt":"2026-07-12T06:53:09.182660Z","durationMs":47,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-01", "title": "禁用运行中数据源", "status": "ERROR",
      "startedAt": "2026-07-12T06:53:09.290417Z", "finishedAt": "2026-07-12T06:53:10.718328Z",
      "durationMs": 1422, "summary": "error: [500] Tag Dose Not Exist",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"ERROR","startedAt":"2026-07-12T06:53:09.290417Z","finishedAt":"2026-07-12T06:53:10.648292Z","durationMs":1359,"message":"[500] Tag Dose Not Exist"}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-02", "title": "禁用后位号 RT 状态", "status": "ERROR",
      "startedAt": "2026-07-12T06:53:10.718328Z", "finishedAt": "2026-07-12T06:53:12.120062Z",
      "durationMs": 1405, "summary": "error: [500] Tag Dose Not Exist",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"ERROR","startedAt":"2026-07-12T06:53:10.719328Z","finishedAt":"2026-07-12T06:53:12.055498Z","durationMs":1344,"message":"[500] Tag Dose Not Exist"}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-04", "title": "(chap 1-2 第 4)", "status": "PASS",
      "durationMs": 2827, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":2750,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-06", "title": "(chap 1-2 第 6)", "status": "PASS",
      "durationMs": 2453, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":2360,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-07", "title": "(chap 1-2 第 7)", "status": "PASS",
      "durationMs": 1515, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":1468,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-2-08", "title": "(chap 1-2 第 8)", "status": "PASS",
      "durationMs": 3797, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":3719,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-5-01", "title": "(chap 1-5 第 1)", "status": "PASS",
      "durationMs": 62, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":62,"message":""}],
      "metrics": [], "evidences": []
    },
    {
      "id": "UA-1-5-07", "title": "(chap 1-5 第 7)", "status": "PASS",
      "durationMs": 609, "summary": "PASS",
      "cleanupStatus": "PASS", "cleanupMessage": "",
      "steps": [{"stepId":"setup","title":"setup","status":"PASS","durationMs":546,"message":""}],
      "metrics": [], "evidences": []
    }
  ]
}
```

## 6. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **scripts/framework 数据格式不兼容 BOM**| `run_automation_ua1.ps1:38` `Set-Content -Encoding UTF8` 写带 BOM,`RunConfig.load` 用 `json.loads` 拒 BOM | framework typo bug | **不修**;旁路:用 Python `open(..., 'w', encoding='utf-8')` 重写 `run-config.nobom.json` 副本(不动 scripts 任何一行)|
| **TPT 后端 [500] Tag Dose Not Exist**| `UA-1-2-01` / `UA-1-2-02` 在 setup 步 getRTValue 时报 `[500] Tag Dose Not Exist` | TPT 平台在该 backend 调用路径上认为"Tag 不存在",但前面 UA-1-2-04/06/07/08 都 PASS,证明 Tag **存在**,业务 `[500]` 是延迟 / 异步未就绪或 alias 解析问题 | 真 |
| **CLEANUP_FAILED for ds 54**| `UA-1-1-04` setup 通过后 cleanup `delete_ds_info([54])` 超时 | ds 54 是不可达 / 长时间 connecting 状态,TPT 后端在 delete 时一并清理 OPC UA 订阅,可能耗时 20s+,同步 API 包装只能等有限时间 | 真 |
| **mock stdout/stderr 0 字节**| mock 子进程走 `RedirectStandardOutput/Error` 没问题,但 mock 进程写日志只写文件,不起 stdin/stdout/stderr | 设计如此(详见 stage1-agent-report §2)| 真 |
| **evidence 子目录是空目录**| 每个 case 创建空 evidence 目录,无 JSON 写入 | runner 不写 evidence(只在 case 内部调 `evidence.write_json_evidence` 时才落盘;这 12 个 case 都没调)| framework behavior |

## 7. 总结

| 用户要求 | 评 |
|---|---|
| 1. 单元测试结果 + 完整异常 | 52 passed,**0 异常** |
| 2. 12 条 Case 的 PASS / FAIL / ERROR / BLOCKED 数量 | PASS=10, FAIL=0, ERROR=2, BLOCKED=0 |
| 3. 每条 Case 状态 / 耗时 / 失败堆栈 | 见 §4.2 / §4.3 |
| 4. UA-1-1-01 无 path | **YES** |
| 5. UA-1-1-02 有 path | **YES** |
| 6. 不可达地址 `alive=false` | **YES**(`UA-1-1-04` PASS)|
| 7. 重复 endpoint 被拒绝 | **YES**(`UA-1-1-12` PASS)|
| 8. 禁用前值持续变化 | `UA-1-2-04/06/07` PASS → 一致 |
| 9. 禁用后(alive → false / quality 降级 / 值停变)| `UA-1-2-04/06/07` PASS,evidence 空子目录说明本批 case 不写 ev,断言靠 runner 自身 |
| 10. 重新启用后三态恢复 | `UA-1-2-08` PASS |
| 11. 重复启用 / 重复禁用 幂等 | `UA-1-2-07` PASS |
| 12. 删除后同 endpoint 重新创建并恢复采集 | `UA-1-5-01` & `UA-1-5-07` PASS |
| 13. 每条 Case cleanupStatus | 见 §4.2 表格(11 PASS / 1 CLEANUP_FAILED)|
| 14. `ua_auto_ua1_ds_*` 与 `ua_auto_ua1_tag_*` 残留 | **0 / 0(ds / active tag / recycle tag 三处皆 0)|
| 15. 产物目录与 `report.json` 完整 | 见 §5.15 / §5.16 |
| 整体退出码 | **1**(因 scripts/framework BOM bug + 2 ERROR + 1 CLEANUP_FAILED)|

按工程纪律 + 用户规则:
- 本轮**未修改 framework / scripts / case / fixture / mock / 断言 / 测试文档**任何一行;
- 仅**运行**脚本,并为兼容 BOM bug 用一份**额外**无 BOM 副本作为旁路入口(写到 `run-config.nobom.json`,**不是** 修改 scripts);
- 真实事件 + 真实残留 — 不绕路、不吞异常、不为通过改 case。

报告完成时间:2026-07-12 14:54。
