# Ray 平台接口探查清单 v2

> 目标:找一个能**一次请求拿全量 worker / Actor**的接口,
> 代替当前逐节点调用 `/nodes/{id}`(N 个节点 = N 次请求)。
> 找到批量接口 → 请求数从 N 降到 1~2,几百节点也能 5 秒采完,且不阉割"全量 5 秒"需求。
>
> 平台地址:当前环境 `http://10.30.144.41:32549`(生产环境替换为你的地址)
> 探查方式:浏览器 F12 或 curl,内网免登无需 cookie。

---

## 核心方向(最重要)

Ray Dashboard 的批量 actor/worker 来源,**正确目标几乎一定不是 `/nodes` 系列,而是 State API**。

| 路径层级 | 当前方案(反向组装) | Ray 原生设计(直接查 state) |
|---|---|---|
| 集群 | `/nodes` | `/api/v0/state/nodes` |
| actor | `/nodes/{id}.actors` | `/api/v0/state/actors` |
| worker | `/nodes/{id}.workers` | `/api/v0/state/workers` |

当前采集器是"从 node 反向组装 worker/Actor",Ray 原生更合理的是"直接查 state API,返回 flat list"。**State API 天然就是全局批量接口**,不嵌套在 node 里,由 dashboard backend 直接查 GCS/state store。

---

## 〇、已知基线(已确认,不用再查)

| 接口 | 状态 | 说明 |
|---|---|---|
| `GET /nodes?view=summary` | ✅ 有 | 全部节点硬件,含 raylet(nodeId/state/GPU),**但不含 worker/Actor** |
| `GET /nodes/{id}` | ✅ 有 | 单节点详情,含该节点的 workers[] + actors{} |
| `GET /api/cluster_status` | ✅ 有 | 集群调度资源 |
| `GET /api/jobs/` | ✅ 有 | 作业列表 |
| `GET /api/version` | ✅ 有 | 版本 |
| `GET /api/actors` | ❌ 404 | 被平台接管,Actor 数据目前只在 `/nodes/{id}` 里 |

---

## 一、最高优先级:State API v0(最可能的根治入口)

这一层是 Ray Dashboard 原生的全局批量接口。逐个试,记录 HTTP 状态码 + 返回前 200 字符:

```bash
curl -i http://10.30.144.41:32549/api/v0/state/actors
curl -i http://10.30.144.41:32549/api/v0/state/workers
curl -i http://10.30.144.41:32549/api/v0/state/nodes
curl -i http://10.30.144.41:32549/api/v0/state/cluster_info
curl -i "http://10.30.144.41:32549/api/v0/state/actors?view=summary"
curl -i "http://10.30.144.41:32549/api/v0/state/actors?filter=alive"
```

### 命中判断标准(关键)

**✔ 成立(找到批量接口):** 返回是 flat list,actor/worker 直接平铺,不嵌在 node 里:

```json
[ { "actor_id": "...", "node_id": "..." }, { "actor_id": "...", "node_id": "..." } ]
```
或
```json
{ "actors": [ ... ] }
```

**❌ 不成立:** 返回仍是 node list,或 actor 仍嵌在 node 内。

> 只要命中任意一个 state 接口返回 flat list,就是我们要的解——请求数从 N 降到 1。

---

## 二、次优先:GCS / internal dashboard proxy 层

部分 Ray 版本 dashboard 有一层 GCS proxy,也返回全局数据。试:

```bash
curl -i http://10.30.144.41:32549/api/gcs/actors
curl -i http://10.30.144.41:32549/api/gcs/nodes
curl -i http://10.30.144.41:32549/api/v0/actors
curl -i http://10.30.144.41:32549/api/v0/workers
```

命中标准同第一节(flat list 即可)。

---

## 三、补充:worker_group / task 维度(可选增强)

有些 worker 不在 node 的 worker list 里,而在 task events 或 runtime env groups。优先级低,顺手探:

```bash
curl -i http://10.30.144.41:32549/api/v0/state/worker_groups
curl -i http://10.30.144.41:32549/api/v0/state/task_events
```

---

## 四、兜底:平台自定义批量接口 + /nodes 其他 view

如果 State API 全 404,再试平台可能改写的路径和 `/nodes` 的其他 view 参数:

```bash
# 平台自定义命名(平台改写了 /nodes,可能也改写了 actors/workers)
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/actors"
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/actors?view=summary"
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/workers"
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/workers?view=summary"

# /nodes 的其他 view(看是否带 workers/actors)
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/nodes?view=detail"
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/nodes?view=full"
curl -s -o /dev/null -w "%{http_code}" "http://10.30.144.41:32549/nodes?view=all"
```

若 `/nodes?view=detail|full` 返回 200,看是否含 workers/actors 字段:

```bash
curl -s "http://10.30.144.41:32549/nodes?view=detail" | python -m json.tool | head -50
```

---

## 五、最可靠的线索:看前端实际调什么接口

平台前端能显示 Actor 列表和 worker 列表——**它前端拿数据时调的接口,就是我们要找的**。前端能显示就证明接口存在,这比猜路径准。

操作:

1. 浏览器打开平台 `http://10.30.144.41:32549/`
2. **F12** → **Network(网络)** 标签 → 勾 **Fetch/XHR**
3. 点进**能看到 Actor 列表**的页面,看 Network 新请求的 URL + Response 结构
4. 切到**能看到 worker/进程列表**的页面,再看 Network 请求 URL + Response

> 注意:如果前端调的也是 `/nodes/{id}` 逐个拉(和你采集器一样),那说明平台自己也没用批量接口,State API 可能确实没暴露——这时再走 fallback。

---

## 六、需要你回传给我的内容

按优先级填(能填多少填多少):

### 6.1 State API(第一节,最重要)

| 路径 | 状态码 | 返回前 200 字符(若 200) | 是否 flat list |
|---|---|---|---|
| `/api/v0/state/actors` | | | |
| `/api/v0/state/workers` | | | |
| `/api/v0/state/nodes` | | | |
| `/api/v0/state/cluster_info` | | | |
| `/api/v0/state/actors?view=summary` | | | |
| `/api/v0/state/actors?filter=alive` | | | |

### 6.2 GCS 层(第二节)

| 路径 | 状态码 | 是否 flat list |
|---|---|---|
| `/api/gcs/actors` | | |
| `/api/gcs/nodes` | | |
| `/api/v0/actors` | | |
| `/api/v0/workers` | | |

### 6.3 前端实际调用的接口(第五节)

- Actor 列表页调的接口 URL:________________
- Actor 列表页返回 JSON 结构(数组?对象?字段):________________
- worker/进程列表页调的接口 URL:________________
- worker/进程列表页返回 JSON 结构:________________
- 前端是逐个 `/nodes/{id}` 拉,还是有批量接口?:________________

---

## 七、找到批量接口后的改法(给你心里有数)

如果 State API 命中(比如 `/api/v0/state/actors` 返回 flat Actor 列表):

- 请求数:N(逐节点)→ 1(批量 actors)+ 1(workers)+ 1(cluster)+ 1(jobs)= 4 次
- detail 周期:16 个 `/nodes/{id}` + cluster + jobs = 18 次 → **4 次**
- 几百节点也只需 4 次请求,5 秒轻松完成
- **不阉割需求**:全量、5 秒、worker/Actor 都有
- 那个 4 秒慢节点的问题也绕过去了(不逐个 detail,就不逐个触发 Head 问 agent)

如果 State API 全 404、前端也是逐个拉 → 再讨论 fallback(并发拉满 + 修慢节点),那也不阉割需求,只是优化。**但先查 State API,别预设它不存在。**
