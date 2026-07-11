# ua_tpt_loop

> 把"ua_mocker 节点 → tpt 数据源 → tpt 位号 → 历史值"这条路径走通的闭环检查工具。
>
> **当前版本**：v0.1.0
>
> designed by yzc

---

## 1. 这是什么

ua_mocker 起一个 OPC UA Server 提供模拟数据；ibd-data-hub (tpt) 通过 `ds-info` 把它当数据源接入，再通过 `tag-info` 声明要从这个数据源读哪些位号。

**ua_tpt_loop** 走 4 步验证这条链路是否真的通：

| Step | 检查项 | 失败时 | 成功时 |
|---|---|---|---|
| 1 | ua_mocker 节点可达 + 节点存在 | OPC UA 不可达 / 节点缺失 | 节点清单 + sample 值 |
| 2 | tpt 数据源已注册（按 URL 查 ds-info） | dsTarUrl 不在 ds-info | ds_id + alive 状态 |
| 3 | tpt 位号已注册（按 dsId + tagName 查 tag-info） | tag 缺失 | tag_id 列表 |
| 4 | tpt 真的在从数据源拉数据（按 get_history_value 验证） | 最近窗口内 0 个数据点 | 数据点条数 + 最新延迟 |

缺哪一步就**自动补**（`--no-auto-register` 关掉则只查不补），最后报"闭环通 / 不通"。

---

## 2. 快速上手

```cmd
# 自动注册缺失的 ds + tag，验证数据流
python -m ua_tpt_loop check ^
  --mocker-yaml ua_mocker/config_example.yaml ^
  --tpt-url http://10.10.58.153:31501 ^
  --tpt-user admin ^
  --tpt-password 123456 ^
  --sample-seconds 10
```

预期输出：

```
[1/4] ua-server node    : PASS  (opc.tcp://0.0.0.0:18950/ua_mocker/, 4 nodes, sample=...)
[2/4] tpt data source   : PASS  (ds_id=5, name=mocker_0.0.0.0_18950, alive=True)
[3/4] tpt tags          : PASS  (4/4 tags registered)
[4/4] tpt data flow     : PASS  (4/4 tags have data in last 10s)

All 4 steps passed in 12.4s. Loop is closed.
```

退出码 0 = 闭环通，非 0 = 某步失败。

---

## 3. 命令行参数

```
python -m ua_tpt_loop check
  --mocker-yaml PATH        # ua_mocker 的 YAML 组态（推荐；自动解析 host/port/节点清单）
  --mocker-url URL          # 或者直接给 OPC UA endpoint（不读 YAML）
  --mocker-nodes N1 N2 ...  # 直接给节点名（配合 --mocker-url）
  --tpt-url URL             # tpt 平台 base URL（必填）
  --tpt-user USER
  --tpt-password PWD
  --tpt-tenant-id ID        # HTTPS 多租户时填；HTTP 单租户留空
  --sample-seconds N        # 数据流验证窗口（默认 10）
  --no-auto-register        # 缺 ds / tag 时只报告不补
  --skip-step1              # 跳过 OPC UA 检查（仅 tpt 端）
  --opcua-public-host HOST  # tpt 用来连 ua_mocker 的 host（覆盖 YAML 里的 host；详见 §6）
  --verbose                 # 详细输出
```

---

## 4. 程序化用法

```python
from ua_tpt_loop import check_loop, MockerSpec

result = check_loop(
    mocker=MockerSpec.from_yaml("ua_mocker/config_example.yaml"),
    tpt_url="http://10.10.58.153:31501",
    tpt_user="admin",
    tpt_password="123456",
    sample_seconds=10,
    auto_register=True,
    opcua_public_host="10.30.70.77",   # 可选；tpt 用来连 ua_mocker
)
print(result.summary())   # "All 4 steps passed in 12.4s. Loop is closed."
print(result.is_closed)   # True / False
for step in result.steps:
    print(step.name, step.passed, step.details)
```

---

## 5. 命名约定（必读）

ua_tpt_loop 在 tpt 上注册位号时遵循以下约定（见 `tpt_api/README.md` §5）：

- **`tagBaseName`（底层位号名）= `"{namespace_index}_{node_name}"`**
  - 例：ua_mocker 的 `namespace_index: 1` + 节点 `loop_demo_1` → `tagBaseName = "1_loop_demo_1"`
- **`tagName`（系统位号名）= 同样形式**（与 tagBaseName 同名）

> **坑警告**：
> - 如果不按这个约定，tpt 知道有这个 tag，但**读不到数据**（Step 3 PASS / Step 4 FAIL）
> - 历史平台数据遵循此约定（如 `1_FIC202_RATE.VALUE`）

---

## 6. 已知限制

- **ua_mocker 必须先起**：本工具只验证，不起服务。要么自己起 `ua_mocker.exe config.yaml`，要么用别的 OPC UA server
- **mocker YAML 的 `name + count` 命名约定**：`name="tag1"` + `count=3` → 节点 `tag11`/`tag12`/`tag13`（按 ua_mocker/server_main.py:35 `_node_id_string` 的实现）
- **节点名里不能含 `:`**（tpt 端 tagName 不允许）；含特殊字符的 mocker 节点会跳过
- **data-hub 拉值有延迟**：默认 `--sample-seconds 10` 给 10s 缓冲；如果数据源刷得慢，调大
- **网络拓扑（Step 4 的关键约束）**：
  - **Step 1** 用 YAML 里的 host（`0.0.0.0` 自动翻译成 `127.0.0.1`）→ 验证 ua_mocker 节点在本地可达
  - **Step 2/3/4** 用注册到 tpt 的 URL → tpt 用这个 URL 主动连 ua_mocker
  - 如果 ua_mocker 跑在和 tpt **不同机器**或 tpt 拿 `127.0.0.1` 连不到，**必须用 `--opcua-public-host <host>` 指定 tpt 能到达的地址**
  - 如果 ua_mocker 跑在和 tpt 同一台机器，`--opcua-public-host 127.0.0.1` 通常就够
  - 网络不通时 tpt 端 ds-info 的 `alive` 字段会是 `False`，Step 4 必然失败；这时先确认 tpt 能用那个 URL 连上 ua_mocker 再跑工具
- **String / DateTime 节点**：tpt tag 不支持这两种类型，会在 Step 3 报告里标 `skipped(tpt_unsupported)`，不会注册

---

## 7. examples 目录

| 文件 | 用途 | 何时用 |
|---|---|---|
| `tiny_mocker_config.yaml` | 3 节点最小 mocker 配置（Double, `change=true`） | 跑 `check` 或重连测试的标配输入 |
| `timing_three.py` | 单次精确测 3 件事（discover / reconnect / data_gap） | 快速验证重连行为 |
| `timing_aggregate.py` | 跑 N 次（默认 10）取统计 | 生产数据 / SLA 报告 |

> 早期版本的 `reconnect_test.py` 和占位空文件 `reconnect_timing.py` 已删除（被上面两个取代）。

---

## 8. tpt 重连测试

`tpt` 的 OPC UA client 在 server 失联时会自动重连。下面用 `examples/timing_aggregate.py` 跑 10 次得到实测数据。

### 8.1 测试方法

每次 iteration：
1. 起 `ua_mocker`，等 tpt 标 `alive=True`（基线）
2. 杀 `ua_mocker`，**1s 轮询**到 `alive=False`（记录发现耗时）
3. 重启 `ua_mocker`，**1s 轮询**到 `alive=True`（记录重连耗时）
4. 继续轮询到第一个新数据点入库（记录数据中断时长）

### 8.2 实测统计（10 次）

| # | 问题 | min | median | **mean** | p95 | max |
|---|---|---|---|---|---|---|
| 1 | server 死后客户端多久发现 alive=False | 55.2s | 57.9s | **58.3s** | 62.9s | 62.9s |
| 2 | 发现后多久重连成功 alive=True | 56.8s | 59.7s | **59.8s** | 63.1s | 63.1s |
| 3 | 数据中断多久（appTime 差） | 110s | 120s | **122s** | 170s | 170s |

> 测试环境：tpt @ `http://10.10.58.153:31501`，ua_mocker @ `10.30.70.77:18950`，单个数据源（ds_id=9，3 个 `1_loop_demo_*` tag）

### 8.3 关键发现

1. **tpt 不是严格 30s 周期，是 ~60s 周期**：
   - discover 均值 58.3s
   - reconnect 均值 59.8s
   - 都接近 60s（不是用户最初以为的 30s）
   - 推测：tpt 探测周期 30s，发现/重连包含"探测+下次重试"，所以总延迟 ~60s

2. **数据中断 ≈ discover + reconnect**：
   - 122s ≈ 58s + 60s（再加 ~4s 入库延迟）
   - **没有额外数据丢失**——重连成功后立刻有新数据

3. **稳定性**：
   - discover / reconnect 方差小（55-63s）→ tpt 机制稳定
   - 偶有 170s 离群值 → 某次 tpt 采集延迟变大（不常见，10 次中 1 次）

### 8.4 怎么跑

```cmd
cd F:\github\supcon_tools\ua_tpt_loop

:: 单次快速验证
python examples\timing_three.py

:: 10 次取统计
python examples\timing_aggregate.py --count 10
```

> 总耗时：~25-35 分钟（10 次 × ~2 min/次）

### 8.5 推论

- **可用性**：tpt 对 ua_mocker 故障**自动恢复**，无需人工干预
- **最长数据中断 ~3 分钟**（含离群）
- **重试周期 ~60s**（不是用户原以为的 30s）
- **要更短中断**：改 tpt 端配置（缩短探测/重连周期）
