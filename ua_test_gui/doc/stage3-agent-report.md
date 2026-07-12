# stage3-agent-report.md — UA 自动化 Stage 3 (最小真实数据流) 真实执行报告

## 1. Stage 3 退出码

```text
exit code: 1
```

> `scripts/run_automation_stage3.ps1` 因 step `tpt-dataflow-probe` **FAIL**(TPT 业务码 `A0001 Duplicate data source address` 在 `add_ds_info` 时抛出),脚本 finally 块把退出码写为 1。

## 2. 产物目录绝对路径

```
F:\github\supcon_tools\output\automation_stage3_20260712_114601
```

文件清单(已 ls 确认):

```text
mock-probe.json          1 224     (local-mock-probe)
mock-probe.log           2 454     (同 stdout tee)
mock.stderr.log          0         (mock 子进程 stderr)
mock.stdout.log          0         (mock 子进程 stdout)
pytest.log               204       (unit-tests)
stage3-result.json       1 595     (脚本主产物)
transcript.log           3 350     (PowerShell Start-Transcript)
ua_mocker_20260711.log   14 094 420
ua_mocker_20260712.log   5 024 002
```

> **注意:** `dataflow-probe.json` 和 `dataflow-probe.log` **未在产物目录里出现**。原因见 §6(catch 后 tee + `$ErrorActionPreference=Stop` 让 PowerShell 在 Python `path.write_text()` 行被 SIGPIPE 杀掉之前先把进程杀掉;transcript log 已捕获到 `TerminatingError(python.exe):...Duplicate data source address` 后 PS 终止)。
> 因此 §4 / §5 给出的是本次独立手动重跑 `python -m ua_test_harness.dataflow_probe --output <temp>.json` 拿到的同一文件,**不是 stage3 脚本本身产物的复制**;内容与脚本那次产生的应当完全一致(同一 endpoint 同一冲突 + 同一 login OK + 同一 probe_exception)。
> 如果你视作"篡改",请直接跳看 §6 末尾:脚本运行那次确实没写出文件,transcript 仅有异常一行。

## 3. `stage3-result.json` 完整内容

```json
{
    "schemaVersion":  1,
    "generatedAt":  "2026-07-12T11:46:10.3494506+08:00",
    "repoRoot":  "F:\\github\\supcon_tools",
    "baseUrl":  "http://10.10.58.153:31501/",
    "username":  "admin",
    "tenantId":  "",
    "localIp":  "10.30.70.77",
    "passwordPresent":  true,
    "steps":  [
        { "name":  "unit-tests",            "status":  "PASS", "startedAt":  "2026-07-12T11:46:02.0336188+08:00", "finishedAt":  "2026-07-12T11:46:05.3464098+08:00" },
        { "name":  "local-mock-probe",      "status":  "PASS", "startedAt":  "2026-07-12T11:46:07.4277292+08:00", "finishedAt":  "2026-07-12T11:46:09.3104491+08:00" },
        { "name":  "tpt-dataflow-probe",    "status":  "FAIL",
          "startedAt":  "2026-07-12T11:46:09.3114496+08:00", "finishedAt":  "2026-07-12T11:46:10.2848853+08:00",
          "error":  "业务 code 非 00000: POST http://10.10.58.153:31501/ibd-data-hub-web-v2.2/api/ds-info/add -> code=A0001 msg=[A0001]Client error:Duplicate data source address" }
    ],
    "fatalError":  "业务 code 非 00000: POST http://10.10.58.153:31501/ibd-data-hub-web-v2.2/api/ds-info/add -> code=A0001 msg=[A0001]Client error:Duplicate data source address",
    "status":  "FAIL"
}
```

## 4. `dataflow-probe.json` 完整内容

> 文件未在 stage3 产物目录里写出(原因见 §2 / §6)。下面贴出的内容来自本报告生成前**独立手动调用相同 `python -m ua_test_harness.dataflow_probe --base-url ... --local-ip 10.30.70.77 --timeout 90`** 得到的 `C:\Users\yuzechao\AppData\Local\Temp\opencode\dataflow-probe.json`。

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:47:43.379748Z",
  "baseUrl": "http://10.10.58.153:31501/",
  "username": "admin",
  "tenantId": "",
  "passwordPresent": true,
  "localIp": "10.30.70.77",
  "datasource": {
    "name": "ua_auto_flow_20260712_114743",
    "endpoint": "opc.tcp://10.30.70.77:18960/ua_mocker/"
  },
  "tag": {
    "name": "ua_auto_flow_tag_20260712_114743",
    "baseName": "smoke_change_1"
  },
  "checks": [
    { "name": "login", "ok": true },
    {
      "name": "probe_exception",
      "ok": false,
      "error": "TptAPIError: [A0001] [A0001]Client error:Duplicate data source address",
      "traceback": "Traceback (most recent call last):\n  File \"F:\\github\\supcon_tools\\ua_test_harness\\dataflow_probe.py\", line 84, in probe\n    ds = add_ds_info(\n         ^^^^^^^^^^^^\n  File \"F:\\github\\supcon_tools\\tpt_api\\python\\tpt_api\\datahub.py\", line 1278, in add_ds_info\n    return api._request(\"POST\", DataHubDsInfoAdd, body=body, wrap=False)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"F:\\github\\supcon_tools\\tpt_api\\python\\tpt_api\\client.py\", line 83, in _request\n    raise exc\ntpt_api.errors.TptAPIError: [A0001] [A0001]Client error:Duplicate data source address\n"
    }
  ],
  "cleanup": [
    {
      "name": "verify_cleanup",
      "ok": true,
      "datasourceRemaining": [],
      "tagRemaining": []
    }
  ],
  "elapsedMs": 578.0,
  "ok": false
}
```

### 4.1 行为解读

| check | 含义 | 实测 | 期望 |
|---|---|---|---|
| login | POST /login | **PASS** | PASS |
| create_datasource | add_ds_info(ds_name=ua_auto_flow_20260712_114743, ds_type=REAL_TIME_DB, ds_sub_type=OPC_UA_SERVER, ds_tar_url=opc.tcp://10.30.70.77:18960/ua_mocker/) | **FAIL:A0001 Duplicate data source address**(被 catch 后写入 `probe_exception` 项)| HTTP 200 + 返回 id |
| ~~datasource_alive~~ | 轮询等 alive=true | **未执行**(因 create 步抛异常)| True |
| ~~create_tag~~ | add_tag → 等存在 | **未执行** | HTTP 200 + 返回 id |
| ~~query_tag~~ | list_tags | **未执行** | records 非空 |
| ~~read_rt_first~~ | get_rt_value 第一次 | **未执行** | quality 非空 |
| ~~read_rt_changed~~ | get_rt_value 第二次,值应不同 | **未执行** | value != first |
| verify_cleanup (cleanup 子表) | list_ds/list_tags 过滤 ua_auto_flow_* | **PASS**(`datasourceRemaining:[], tagRemaining:[]`)| 残留 = 0 |

**整体 `ok=false`**,所以 `main()` 返回非零退出码。

### 4.2 位号创建请求 / 响应中的非敏感字段

位号未创建(`create_tag` 未执行),所以**没有位号请求 / 响应数据可贴**。

数据源请求(脚本内 add_ds_info 实际传参 / TPT 响应):

| 字段 | 值 |
|---|---|
| 请求:`ds_name` | `ua_auto_flow_20260712_114743` |
| 请求:`ds_type` | `1` (DsTypes["REAL_TIME_DB"]) |
| 请求:`ds_sub_type` | `4` (DsSubTypes["OPC_UA_SERVER"]) |
| 请求:`ds_tar_url` | `opc.tcp://10.30.70.77:18960/ua_mocker/` |
| 响应 | TPT 返回业务码 `A0001 msg=[A0001]Client error:Duplicate data source address`,未返回 dsId / dsName / dsType |
| `dataType` / `tagName` / `groupId` / `frequency` / `needPush` / `isVector` / `onlyRead` / `tagDesc` 等位号字段 | **未发送**(因 `create_datasource` 失败后整段 try 终止)|

## 5. `dataflow-probe.log` 完整内容

文件未在 stage3 产物目录里写出(原因见 §2 / §6)。下面贴出的是独立手动跑得到的 `C:\Users\yuzechao\AppData\Local\Temp\opencode\dataflow-probe.log`,只是 `dataflow-probe.json` 的 stdout 镜像(Tee-Object 的标准行为),所以**与 §4 内容字节级相同**:略。

注意 stdout 之前有一段 tpt_api logger 走 stderr 的额外行:

```text
业务 code 非 00000: POST http://10.10.58.153:31501/ibd-data-hub-web-v2.2/api/ds-info/add -> code=A0001 msg=[A0001]Client error:Duplicate data source address
```

这是 `tpt_api.client._request` 在 raise 前调用 `log.error(...)` 走 stderr 抛出来的(走 Python logging 默认 handler),不是 dataflow_probe.py 写的。这是这一行造成 PowerShell `$ErrorActionPreference=Stop` 触发 `TerminatingError(python.exe)`,把 tee 链路提前断开,`path.write_text()` 未能落盘。

## 6. `mock-probe.json`(Stage 3, local-mock-probe)

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:46:08.044543Z",
  "endpoint": "opc.tcp://127.0.0.1:18960/ua_mocker/",
  "namespaceIndex": 2,
  "checks": [
    { "name": "browse_mocker_root",    "ok": true,
      "objectChildren": ["QualifiedName(NamespaceIndex=0, Name='Locations')","QualifiedName(NamespaceIndex=0, Name='Server')","QualifiedName(NamespaceIndex=0, Name='Aliases')","QualifiedName(NamespaceIndex=2, Name='mocker')"] },
    { "name": "browse_mocker_children","ok": true, "count": 1, "children": ["QualifiedName(NamespaceIndex=2, Name='mocker_0')"] },
    { "name": "read_static",           "ok": true, "nodeId": "ns=2;s=smoke_static_1", "actual": 12.5,  "expected": 12.5 },
    { "name": "write_readback",        "ok": true, "nodeId": "ns=2;s=smoke_static_1", "actual": 42.25, "expected": 42.25 },
    { "name": "changing_value",        "ok": true, "nodeId": "ns=2;s=smoke_change_1", "before": 2, "after": 4, "waitSec": 1.2 }
  ],
  "elapsedMs": 1234.0,
  "ok": true
}
```

> 这就是最小 ua_mocker 自检结果,**全部 PASS**,ElapsedMs 1234ms,说明 ua_mocker 进程已稳定监听 0.0.0.0:18960 且 OPC UA 协议正常。

## 7. pytest 结果

```text
..................................                                       [100%]
34 passed in 2.51s
```

`ua_test_harness.unit_tests` 全部 34 passed,无 skip / xfail / error。

## 8. Mock 最新相关日志(ua_mocker_20260712.log,本次 stage3 启动段 11:46:06 ~ 11:46:08)

```text
2026-07-12 11:46:06 [INFO] config_loader: 动态加载成功: F:\github\supcon_tools\ua_mocker\smoke.yaml
2026-07-12 11:46:06 [INFO] asyncua.server.internal_session: Created internal session Internal
2026-07-12 11:46:06 [INFO] server_main: OPC UA 端点: opc.tcp://0.0.0.0:18960/ua_mocker/
2026-07-12 11:46:06 [INFO] server_main: 服务器已启动,cycle=500 ms,change 节点数=1
2026-07-12 11:46:06 [WARNING] asyncua.server.server: No encrypting policy available, password may get transferred in plaintext
2026-07-12 11:46:06 [WARNING] asyncua.server.server: Endpoints other than open requested but private key and certificate are not set.
2026-07-12 11:46:06 [INFO] asyncua.server.internal_server: starting internal server
2026-07-12 11:46:06 [INFO] asyncua.server.binary_server_asyncio: Listening on 0.0.0.0:18960
2026-07-12 11:46:07 [INFO] asyncua.server.binary_server_asyncio: New connection from ('127.0.0.1', 34066)
2026-07-12 11:46:07 [INFO] asyncua.server.binary_server_asyncio: Lost connection from ('127.0.0.1', 34066), None
2026-07-12 11:46:07 [INFO] asyncua.server.uaprocessor: Cleanup client connection: ('127.0.0.1', 34066)
2026-07-12 11:46:08 [INFO] asyncua.server.binary_server_asyncio: New connection from ('127.0.0.1', 34088)
2026-07-12 11:46:08 [INFO] asyncua.server.internal_session: Created internal session ('127.0.0.1', 34088)
2026-07-12 11:46:08 [INFO] asyncua.server.uaprocessor: Browse request (User(role=<UserRole.User: 3>, name=None))
2026-07-12 11:46:08 [INFO] asyncua.server.uaprocessor: Read request (User(role=<UserRole.User: 3>, name=None))  (x6)
2026-07-12 11:46:08 [INFO] asyncua.server.uaprocessor: Write request (User(role=<UserRole.User: 3>, name=None))
```

说明:
- mock 11:46:06 启动 + `change 节点数=1`,`Listening on 0.0.0.0:18960`,协议存活
- 11:46:08 收到 mock-probe 的 Browse/Read/Write — `local-mock-probe` 真做了 mock 自检
- 之后 mock 进程被脚本 `finally` 块 `Stop-Process` 结束(mock 即无 11:46 之后的输出)
- **`tpt-dataflow-probe` 阶段没有任何与 mock 的网络连接日志** — 因为 add_ds_info 在数据流探针发起 OPC UA 连接之前就抛 A0001 终止,`wait_ds_alive` 没等到、连接没建立

## 9. 所有异常完整堆栈

仅 1 个真实异常(由 dataflow-probe.py:171 写入 `probe_exception` 详情中,完整见 §4 traceback 字段):

```text
Traceback (most recent call last):
  File "F:\github\supcon_tools\ua_test_harness\dataflow_probe.py", line 84, in probe
    ds = add_ds_info(
         ^^^^^^^^^^^^
  File "F:\github\supcon_tools\tpt_api\python\tpt_api\datahub.py", line 1278, in add_ds_info
    return api._request("POST", DataHubDsInfoAdd, body=body, wrap=False)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "F:\github\supcon_tools\tpt_api\python\tpt_api\client.py", line 83, in _request
    raise exc
tpt_api.errors.TptAPIError: [A0001] [A0001]Client error:Duplicate data source address
```

根因:TPT 后端拒绝在 `opc.tcp://10.30.70.77:18960/ua_mocker/` 上再创建数据源(已存在 1 个)。

## 10. 数据源最终是否达到 `alive=true`?

**否**(因为 `add_ds_info` 抛 A0001,**TPT 拒绝创建**,根本不存在这次 stage3 期望创建的 `ua_auto_flow_20260712_114601` 数据源)。

TPT 上当前与本次 stage3 endpoint 冲突的旧记录(独立 `list_ds_info` 全量查询得到,见 §11):

| id | dsName | dsTarUrl | dsStatus | alive | createTime |
|---|---|---|---|---|---|
| 43 | `ua_auto_ua1_001` | `opc.tcp://10.30.70.77:18960/ua_mocker/` | 1 | **False** | 2026-07-12 10:01:58 |

(此 ds 已存在但 `alive=false`,因为我们本次启动的 mock 实例与之 timestamp 不同,OPC UA server 的 endpoint 身份不稳定 / 或 TPT 端 connect 到老 mock 时端点未 refresh,与 stage3 的 mock 是同一 endpoint URL 但不同 server 进程,但 TPT 把它视为"已存在 endpoint"拒绝重名)

## 11. `ua_auto_flow_*` 是否残留?

**残留数 = 0**(ds / tag / recycle 三处全部为 0)。

实测(独立全量查询 + 过滤)`C:\Users\yuzechao\AppData\Local\Temp\opencode\stage3_residual.txt`:

```text
=== DS ua_auto_flow_* === 0
=== TAG ua_auto_flow_* (active) === 0
=== TAG ua_auto_flow_* (recycle) === 0
```

(`dataflow_probe` 自己的 `verify_cleanup` 也独立给出 `datasourceRemaining: [], tagRemaining: []` — 与外层独立查询互证)

附:全量 ds 列表(只看 dsName / id,确认现场):

```text
dsId=46 | ua_auto_ua1_1_04    | opc.tcp://127.0.0.1:1/ua_mocker/                       | 1 | False
dsId=45 | ua_auto_ua1_1_03b   | opc.tcp://10.30.70.77:18960/ua_mocker/ua_mocker_b/   | 1 | False
dsId=44 | ua_auto_ua1_1_02    | opc.tcp://10.30.70.77:18960/ua_mocker/ua_mocker_extra/ | 1 | False
dsId=43 | ua_auto_ua1_001     | opc.tcp://10.30.70.77:18960/ua_mocker/                | 1 | False   ← 抢占 stage3 endpoint
dsId=40 | mocker_18950        | opc.tcp://10.30.70.77:18950/ua_mocker/                | 1 | True
dsId=36 | zzfmock             | opc.tcp://10.10.58.117:18959                          | 1 | True
dsId=12 | 153                 | opc.tcp://10.10.58.117:18950                          | 1 | True
dsId=8  | 72                  | 10.30.144.72:25430                                   | 1 | True
dsId=4  | tpt_api_test_1783326041 | opc.tcp://192.168.99.42:18950                    | 1 | False
dsId=2  | omc167              | opc.tcp://172.20.58.167:18950                         | 1 | True
dsId=1  | omc105              | opc.tcp://10.10.58.105:18950                         | 1 | True
```

> 其中 `ua_auto_ua1_*` 是过往 UA-1-1 试验性 case 留下的 TPT 测试数据;非本次 stage3 创建 → 不算 stage3 残留。

## 12. 异常归类(不修不绕,如实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **环境问题** | dataflow-probe 因 `add_ds_info` 拒绝 endpoint 重名而失败 | TPT 后端把 `opc.tcp://10.30.70.77:18960/ua_mocker/` 视为唯一键,dsId=43 的旧 `ua_auto_ua1_001` 已经占住(见 §10 / §11)| **不修、不绕**;按用户纪律保留真实结果 |
| **第三方依赖问题(轻微)** | ua_mocker 启动期警告:`No encrypting policy available` + `Endpoints other than open requested but private key and certificate are not set` | mock 不带证书,SecurityPolicy 走 None | 不修(本任务不验鉴权)|
| **第三方依赖问题(轻微)** | asyncua 启动期 `add_node ... parent ... does not exists`、大量 `Instantiate: Skip node without modelling rule ...` informational 日志 | asyncua 初始化顺序问题,服务仍可监听 | 不修 |
| **测试框架问题** | `dataflow-probe.json` / `.log` 未在 stage3 产物目录里写出 | tpt_api logger 把 A0001 错误打到 stderr,PowerShell `$ErrorActionPreference=Stop` 让 tee pipe 提前断开,Python 子进程在 `path.write_text()` 落盘前被 SIGPIPE | **不修**(本报告的纪律是真实记录,不绕为通过;现场有 transcript.log + 独立手工重跑得到 probe JSON 镜像)|
| **数据流进展** | 数据流在"dataflow 探针发起 OPC UA 连接"之前即终止,**未产生 RT 实时值,也无真 alive=true 验证** | endpoint 冲突 | 待用户决策:删除旧 dsId=43 让出 endpoint / 修改 stage3 用单独 mock 端口 / 删除 stage3 的强制 add_ds_info 步骤 |
| **数据流进展** | 未读到第一次、第二次实时值 | 因 probe 没成功运行 alive + create_tag | 见下条 |
| **数据流进展** | 数据源、位号 `ua_auto_flow_*` 残留 = 0 | 这是合规,本次未新增任何 ua_auto_flow_* | 真实记录 |

## 13. 总结

| 步骤 | 状态 | 用时 |
|---|---|---|
| unit-tests | **PASS**(34 passed/2.51s)| 11:46:02 → 11:46:05 |
| local-mock-probe | **PASS**(5/5,1234ms)| 11:46:07 → 11:46:09 |
| tpt-dataflow-probe | **FAIL**(A0001 Duplicate data source)| 11:46:09 → 11:46:10 |
| **整体退出码** | **1** | |

按用户纪律:不修、不绕、不删断言、不改 tpt_api 封装、真实记录。
- `opc.tcp://10.30.70.77:18960/ua_mocker/` 在 TPT 端已被 `dsId=43 ua_auto_ua1_001` 占住 → TPT 拒绝重复创建 → stage3 数据流未真正跑通。
- `ua_auto_flow_*` 残留 = 0;`ua_auto_ua1_*` 不属于本 stage3 产物。

**下次可推进路径**(仅记录,不在本任务范围):

1. 手动 `delete_ds_info(43)`,腾出 endpoint,重跑 stage3。
2. 修改 `dataflow_probe.py` 让 endpoint 优先级先占(选未占用的端口 e.g. 18999 / 18970) — 但这需用户决策改框架,不属本 stage 任务。
3. 增加 stage4:先强制清旧 endpoint 的占用 ds、保证每次 stage3 都用专属端口。

报告完成时间:2026-07-12 11:48。
