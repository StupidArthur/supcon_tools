# TODO: tpt_api (Python) 补充位号值接口

## 背景
仅在 `tpt_api/python` 版本补充接口，边加边调试，定稿。
源：内网 knife4j 接口文档 `http://10.10.58.153:31556/doc.html`。
流程：用户给 URL → 逐一 理解 → 封装 → 验证 → 定稿。

## 4 个目标接口（位号值分组，均为 POST）

| # | 名称 | operationId | 文档 URL |
|---|---|---|---|
| 1 | 位号值采集 | collectTagValueUsingPOST | http://10.10.58.153:31556/doc.html#/default/位号值/collectTagValueUsingPOST |
| 2 | 取位号实时值 | getRTValueUsingPOST | http://10.10.58.153:31556/doc.html#/default/位号值/getRTValueUsingPOST |
| 3 | 取位号历史值 | getHistoryValueUsingPOST | http://10.10.58.153:31556/doc.html#/default/位号值/getHistoryValueUsingPOST |
| 4 | 实时数据库回写位号值 | writeTagValuesUsingPOST | http://10.10.58.153:31556/doc.html#/default/位号值/writeTagValuesUsingPOST |

## 6 步流程（每接口）
拉 OpenAPI 规范 → 理解（method/path/params/request/response/errors）→ 封装（模块函数 + `api` 首参 + `_request` + endpoint 常量 + 类型）→ pytest（httpx.MockTransport）→ 验证（真实接口）→ 定稿（datahub.py 头注释 / `__init__` 导出 / README / user_guide）

## 当前进度

### 已完成
- [x] 1. 拉规范：从 knife4j `/v2/api-docs` 取 swagger2.0，定位 4 个 tag-value 接口
- [x] 2. 理解：method=POST，path=`/api/tag-value/{collectTagValue|getRTValue|getHistoryValue|writeTagValues}`，context-path 前缀 `/ibd-data-hub-web-v2.2/api`（与已有 getHistoryValueFromDB 一致，已验证）
  - `getHistoryValueUsingPOST` ≠ 现有 `get_history_value`（=getHistoryValueFromDB）：前者支持 interval/offset/option + IPage 分页，后者 {tagName:{list,total}} 结构
- [x] 3. 封装：`datahub.py` 已加 4 函数 + 4 个 endpoint 常量
  - `collect_tag_value(api, es_dto, group_id, tenant_id) -> bool`
  - `get_rt_value(api, tag_names=None, tag_info_ids=None, group_id=None, is_from_db=False, option=None, query_time=None) -> list[dict]`
  - `query_history_value(api, tag_names, beg_time, end_time, interval=0, is_second=True, is_source=False, offset=0, option=0, page=1, page_size=10, sort="-appTime") -> dict`（IPage；命名避开已有 `get_history_value`）
  - `write_tag_values(api, values, tag_time=None, quality_code=None) -> dict`
  - wrap：collect/getRT/write = `wrap=True`；query_history = `wrap=False`（带 `requestBase` 分页）
- [x] 4. pytest：`tests/test_datahub.py` 加 4 个测试（body shape + 返回解析），共 12 个全过
- [x] datahub.py 头注释加了 4 个 endpoint 行
- [x] `examples/verify_tag_value.py`（手动验证脚本，环境变量）

### 已完成（续）
- [x] 5. 真实环境验证（base_url=`http://10.10.58.153:31501`，user=admin；注意 base_url **不带** `/tpt-admin/`，那段在 `LoginPath` 常量里，带了会重复成 `tpt-admin/tpt-admin`）
  - get_rt_value ✓ 取到真实值（含 `is_from_db=True` 直读库）
  - query_history_value ✓ `1_test_write` 7 天 total=4718 条，IPage 结构完整
  - write_tag_values ✓ 回写 → `tagNames=['1_test_write']` failMsg 空 → 读回确认落库
  - ⚠️ 读回时机：`query_history_value(is_source=True)` **立即**可查到写入记录（writeTagValues 直接写历史，不受 UA 5s 采集周期限制；实测 +0s 命中，appTime=写入时刻、不在 5s 网格）；`get_rt_value` 写后约 **1 秒**才反映（+0s 旧值、+1s 新值），同脚本写完立刻读会拿旧值
  - collect_tag_value 跳过（esDTO 需现场配置，单测已验 body shape）
  - 注：config.json 当时无保存环境，改用 `examples/verify_tag_value.py` + 环境变量（`DATAHUB_BASE_URL`/`DATAHUB_USER`/`DATAHUB_PASSWORD`/`WRITE=1`）
  - 坑：自动选中的首个 tag `1 test_write`（带空格）是空测试位号（value=None, tagTime=epoch），回写被拒 code=-2144075776；换成 `1_test_write`（下划线）才正常
  - **双向数据流验证**（asyncua 直连源端 ua_player `opc.tcp://127.0.0.1:18950/` `ns=1;s=test_write`，与 datahub tag `1_test_write` 是同一物）：
    - **写值回写源端** ✓：基线 ua_player 节点=123.45（=上一轮 writeTagValues(123.45) 已透到源端）→ `write_tag_values(999.99)` 写 datahub → 2s 后直读 ua_player 节点 = **999.99**。确认 `writeTagValues` 不止写 datahub 历史+当前值，**还把值回写到了 UA 源端服务器**（两点互证：基线 123.45 + 写后 999.99 都来自 writeTagValues）
    - **源端变动→datahub 采集**：OPC UA 直写 555.55 到 ua_player → `get_rt_value` **+1s 即 = 555.55**（远快于 5s 轮询，推测 datahub 对 UA 有订阅/快速刷新维护当前值快照）；`query_history_value` 第一条 555.55 在 **+4s**、第二条 +8s（落在 ~5s 轮询网格，poller 采样落库）。CSV 回放不覆盖注入值（同值不重写），故测量干净
    - **数据流模型（最终）**：writeTagValues 方向 = 直接写历史(+0s) + ~1s 当前值快照 + 回写 UA 源端；源端变动方向 = ~1s 当前值快照（订阅?）+ ~5s 网格 history（轮询）
- [x] 6. 定稿：
  - [x] README §6.3 改名「位号值（tag-value）」+ 加 4 函数行 + `query_history≠get_history` / write 返回说明
  - [x] README §4.3 方法名清单加「位号值」行；§9 验证数 39→43 + 真实环境验证说明
  - [x] `examples/datahub.py` 补 `get_rt_value` + `query_history_value` 只读示例（write/collect 仍指向 verify_tag_value.py）
  - `__init__` 导出无需改（datahub 子模块自动 import，新函数经 `datahub.xxx` 访问）

## 恢复后立即执行
1. ~~跑真实环境验证~~ ✅ 完成（见上）
2. ~~补 README / user_guide~~ ✅ 完成
3. ~~确认单测全过~~ ✅ 43 passed（无回归）

## 关键文件
- `tpt_api/python/tpt_api/datahub.py`（已改：4 函数 + 4 常量 + 头注释）
- `tpt_api/python/tests/test_datahub.py`（已改：+4 测试）
- `tpt_api/python/tpt_api/examples/verify_tag_value.py`（已建）
- 凭据：`~/.ua_tpt_manager/config.json`

## 关键决策
- 新历史值函数命名 `query_history_value`（非 `get_history_value`），避开已有 `get_history_value` = getHistoryValueFromDB
- 4 接口用 dict 透传，未加新类型（`types.py` 不改）
- endpoint 前缀沿用 `DataHubBasePath = /ibd-data-hub-web-v2.2/api`

## 验证脚本（heredoc，分类器恢复后直接跑）
```
cd /tmp && PYTHONIOENCODING=utf-8 python - <<'PY'
import json, os, sys, traceback
from datetime import datetime, timedelta
sys.path.insert(0, r"F:/github/supcon_tools/tpt_api/python")
from tpt_api import AlgAPI
from tpt_api import datahub as dh
d = json.load(open(os.path.expanduser("~/.ua_tpt_manager/config.json"), encoding="utf-8"))
envs = d.get("tpt_envs") or d.get("tptEnvs") or []
env = next((e for e in envs if e.get("password")), None)
assert env, "配置未保存密码"
base_url = env.get("base_url") or env.get("baseUrl")
api = AlgAPI(base_url, timeout=60.0)
api.login(env.get("username",""), env["password"], env.get("tenant_id") or env.get("tenantId") or "")
print(f"环境: {env.get('name')} {base_url} user={env.get('username')} tenant={env.get('tenant_id') or env.get('tenantId')!r}")
tag = dh.list_tags(api, page=1, page_size=5)["records"][0]["tagName"]
print("tagName:", tag)
print("get_rt_value:", len(dh.get_rt_value(api, tag_names=[tag])), "条")
end=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); beg=(datetime.now()-timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
h=dh.query_history_value(api,[tag],beg,end,page=1,page_size=5); print("history total:", h.get("total"))
print("write:", dh.write_tag_values(api,{tag:123.45},tag_time=end,quality_code=192))
PY
```
