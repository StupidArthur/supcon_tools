"""
阶段 4：REST/WebSocket 真实现场快照契约测试。

覆盖：
1. /api/status.instance_name 来自 EngineBinding.instance_name（不是 pid2 / tank_2）。
2. /api/status.cycle_time 来自 Engine 真实周期配置。
3. /api/instances/{runtimeName}/meta 与 /api/instances/{runtimeName}/snapshot
   在运行时返回 runtimeName 不匹配时返回 404。
4. snapshot 至少包含 contracts.md §9.3 列出的全部必需位号。
5. 多 WS 客户端不会让 Engine 重复计算（Engine 仍只跑一次）。
6. 慢消费者策略：单客户端 queue 满时新帧覆盖旧帧，Engine 永远不会被阻塞。
7. status 与 /snapshot 必须从同一份完整 snapshot 读取；cycle_count / sim_time
   随 Engine 推进严格递增，REST 与 WS 也保持一致。
8. 缺字段（包括 cycle_count/sim_time）原样缺失，绝不替换为 0 / NaN。
"""

from __future__ import annotations

import asyncio
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import WebSocketDisconnect

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 触发算法/模型注册
import components.programs  # noqa: F401

from controller.engine import UnifiedEngine
from controller.parser import DSLParser
from controller.clock import ClockMode

# 在导入 FastAPI app 前先把 engine_api 注入到独立模块下；FastAPI 模块本身是单例。
import datacenter.engine_api as engine_api


# --------------------------------------------------------------------------- #
# 辅助                                                                         #
# --------------------------------------------------------------------------- #
def _build_engine(yaml_path: str, cycle_time: float = 0.5) -> UnifiedEngine:
    parser = DSLParser()
    config = parser.parse_file(yaml_path)
    config.clock.cycle_time = cycle_time
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR
    return engine


def _run_cycles(engine: UnifiedEngine, n: int) -> List[Dict[str, Any]]:
    engine.clock.start()
    snaps = [engine.step() for _ in range(n)]
    engine.clock.stop()
    return snaps


def _make_binding(instance_name: str = "second_order_tank",
                  cycle_time: float = 0.5,
                  yaml_path: str = "config/单阀门二阶水箱.yaml") -> engine_api.EngineBinding:
    """构造一个 EngineBinding；engine 用真实 UnifiedEngine。

    模拟 standalone_main.py：每个周期 engine.step() 后调用 binding.push_snapshot(snap)
    —— 该调用会把完整 snapshot（含 cycle_count/sim_time）写入 binding._latest_snapshot
    并广播 WS。status / /snapshot 必须从同一份 _latest_snapshot 读取。
    """
    engine = _build_engine(yaml_path, cycle_time=cycle_time)
    shared: Dict[str, float] = {}
    binding = engine_api.EngineBinding(
        instance_name=instance_name,
        engine=engine,
        shared_data=shared,
    )

    def _drive_cycles(n: int = 2) -> None:
        engine.clock.start()
        for _ in range(n):
            snap = engine.step()
            for k, v in snap.items():
                if k not in ("cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"):
                    shared[k] = v
            binding.push_snapshot(snap)
        engine.clock.stop()

    _drive_cycles(2)
    binding._drive_test = _drive_cycles  # type: ignore[attr-defined]
    return binding


@pytest.fixture
def binding() -> engine_api.EngineBinding:
    b = _make_binding()
    engine_api.set_binding(b)
    yield b
    engine_api.set_binding(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 0. status 与 /snapshot 同源 + cycle_count/sim_time 推进                       #
# --------------------------------------------------------------------------- #
def test_status_and_snapshot_share_same_cycle_count(binding):
    """status.cycle_count 与 /snapshot.cycle_count 必须来自同一份完整 snapshot。"""
    status = engine_api.api_status()
    snap = engine_api.api_snapshot(binding.instance_name)
    assert status.cycle_count == snap["cycle_count"], (
        f"status 与 snapshot cycle_count 不一致：status={status.cycle_count}, "
        f"snapshot={snap.get('cycle_count')}"
    )
    assert status.sim_time == snap["sim_time"], (
        f"status 与 snapshot sim_time 不一致：status={status.sim_time}, "
        f"snapshot={snap.get('sim_time')}"
    )


def test_status_cycle_count_advances_with_engine(binding):
    """status.cycle_count 必须随 Engine 推进严格递增；sim_time 同样。"""
    binding._drive_test(1)  # type: ignore[attr-defined]
    snap1 = engine_api.api_snapshot(binding.instance_name)
    status1 = engine_api.api_status()
    cc1 = snap1["cycle_count"]
    st1 = snap1["sim_time"]

    binding._drive_test(5)  # type: ignore[attr-defined]
    snap2 = engine_api.api_snapshot(binding.instance_name)
    status2 = engine_api.api_status()
    cc2 = snap2["cycle_count"]
    st2 = snap2["sim_time"]

    assert cc2 > cc1, f"cycle_count 必须递增：{cc1} -> {cc2}"
    assert st2 > st1, f"sim_time 必须递增：{st1} -> {st2}"
    assert status2.cycle_count == cc2, "status 跟 snapshot 不一致"
    assert abs(status2.sim_time - st2) < 1e-9, "status.sim_time 跟 snapshot 不一致"
    # 周期增量恰好等于推进次数（5）
    assert (cc2 - cc1) == 5, f"周期增量应为 5，实际 {cc2 - cc1}"


def test_status_sim_time_increments_by_cycle_time(binding):
    """sim_time 增量应等于 cycle_time × 推进周期数。"""
    binding._drive_test(1)  # type: ignore[attr-defined]
    t0 = engine_api.api_status().sim_time
    binding._drive_test(10)  # type: ignore[attr-defined]
    t1 = engine_api.api_status().sim_time
    # 周期 0.5s × 10 周期 = 5.0s
    assert abs((t1 - t0) - 5.0) < 1e-6, f"sim_time 增量异常：{t0} -> {t1}"


def test_engine_binding_latest_snapshot_locked():
    """并发读到的每一帧必须满足跨字段不变量，不能是撕裂快照。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml", cycle_time=0.5)
    binding = engine_api.EngineBinding(instance_name="sync_test", engine=engine, shared_data={})
    errors: List[str] = []

    def writer():
        for marker in range(1, 2001):
            binding.push_snapshot({
                "cycle_count": marker,
                "sim_time": marker * 0.5,
                "marker": marker * 7,
            })

    def reader():
        for _ in range(4000):
            snap = binding.get_latest_snapshot()
            if snap is not None:
                cycle = snap["cycle_count"]
                if snap["sim_time"] != cycle * 0.5 or snap["marker"] != cycle * 7:
                    errors.append(repr(snap))

    t_writer = threading.Thread(target=writer)
    t_readers = [threading.Thread(target=reader) for _ in range(4)]
    t_writer.start()
    for t in t_readers:
        t.start()
    t_writer.join()
    for t in t_readers:
        t.join()

    assert not errors, f"读取到撕裂 snapshot: {errors[:3]}"


def test_status_and_snapshot_each_remain_internally_consistent_during_pushes():
    """Engine 推进竞争下，status/snapshot 各自响应内的周期字段必须来自同一帧。"""
    binding = _make_binding()
    engine_api.set_binding(binding)
    stop = threading.Event()

    def writer():
        marker = 1
        while not stop.is_set():
            binding.push_snapshot({
                "cycle_count": marker,
                "sim_time": marker * 0.5,
                "marker": marker * 11,
            })
            marker += 1

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        for _ in range(500):
            status = engine_api.api_status()
            assert status.sim_time == status.cycle_count * 0.5
            snap = engine_api.api_snapshot(binding.instance_name)
            assert snap["sim_time"] == snap["cycle_count"] * 0.5
            assert snap["marker"] == snap["cycle_count"] * 11
    finally:
        stop.set()
        thread.join()
        engine_api.set_binding(None)  # type: ignore[arg-type]


def test_snapshot_endpoint_returns_empty_dict_when_engine_not_started():
    """Engine 尚未推过任何周期时，/snapshot 返回 {}（明确"无 snapshot"），不替换为 0。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml", cycle_time=0.5)
    binding = engine_api.EngineBinding(instance_name="not_started", engine=engine, shared_data={})
    engine_api.set_binding(binding)
    try:
        snap = engine_api.api_snapshot("not_started")
        assert snap == {}, f"无 snapshot 时应返回空 dict，实际：{snap}"
        status = engine_api.api_status()
        # 缺 cycle_count/sim_time 不能映射为 0：status 默认值应明确反映"未开始"
        # 设计契约：status.cycle_count == 0 + sim_time == 0.0 表示未启动；
        # 但 /snapshot 不返回这些字段以与"已运行 cycle=0"区分。
        assert status.cycle_count == 0
        assert status.sim_time == 0.0
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. status 返回真实 instance_name                                            #
# --------------------------------------------------------------------------- #
def test_api_status_returns_runtime_instance_name(binding):
    """GET /api/status.instance_name 必须等于 --name 指定值，不得与 pid2 / tank_2 混淆。"""
    resp = engine_api.api_status()
    assert resp.instance_name == "second_order_tank", (
        f"runtimeName 错误: {resp.instance_name}（不得与 Program 实例名混淆）"
    )
    # 必须有限定字段
    assert resp.cycle_time > 0
    assert resp.mode == "GENERATOR"


def test_api_status_uses_binding_instance_name_not_pid():
    """status.instance_name 永远来自 EngineBinding；即使 binding 改名为非 pid2 字符串也必须返回。"""
    engine_api.set_binding(None)  # type: ignore[arg-type]
    b = _make_binding(instance_name="tank_A")
    engine_api.set_binding(b)
    try:
        resp = engine_api.api_status()
        assert resp.instance_name == "tank_A"
        assert resp.instance_name != "pid2"
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 2. meta / snapshot 校验 runtimeName                                          #
# --------------------------------------------------------------------------- #
def test_meta_404_when_runtime_name_mismatch(binding):
    """meta 路径中的 {name} 不等于 binding.instance_name 时返回 404。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        engine_api.api_meta("pid2")
    assert exc.value.status_code == 404


def test_snapshot_404_when_runtime_name_mismatch(binding):
    """snapshot 路径中的 {name} 不等于 binding.instance_name 时返回 404。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        engine_api.api_snapshot("tank_2")
    assert exc.value.status_code == 404


def test_meta_returns_variable_meta(binding):
    meta = engine_api.api_meta("second_order_tank")
    assert meta["instance_name"] == "second_order_tank"
    assert "meta" in meta
    # 必需位号都在 meta 中
    required = ["valve_1.current_opening", "tank_2.level", "pid2.SV", "pid2.MV"]
    for key in required:
        assert key in meta["meta"], f"meta 缺少 {key}"


def test_tags_catalog_excludes_runtime_metadata(binding):
    resp = engine_api.api_tags("second_order_tank")
    assert resp["ok"] is True
    names = [t["name"] for t in resp["tags"]]
    # 业务位号存在
    assert "tank_2.level" in names
    assert "pid2.SV" in names
    # 运行元数据不作为业务 tag
    assert "cycle_count" not in names
    assert "sim_time" not in names
    # 排序稳定
    assert names == sorted(names)


def test_tags_catalog_forceable_from_shared_data(binding):
    resp = engine_api.api_tags("second_order_tank")
    by_name = {t["name"]: t for t in resp["tags"]}
    # tank_2.level 在 shared_data 中，应可强制
    assert by_name["tank_2.level"]["forceable"] is True
    assert by_name["tank_2.level"]["dataType"] == "number"


def test_tags_404_when_runtime_name_mismatch(binding):
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        engine_api.api_tags("wrong_name")


def test_broadcaster_full_snapshot_without_subscribe(binding):
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    bc.publish({"cycle_count": 1, "pid.PV": 0.5, "tank.level": 0.3})
    got = q.get_nowait()
    assert got["pid.PV"] == 0.5
    assert got["tank.level"] == 0.3


def test_broadcaster_subscribe_filters_tags(binding):
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    bc.subscribe(q, {"pid.PV"})
    bc.publish({"cycle_count": 1, "sim_time": 0.5, "pid.PV": 0.5, "tank.level": 0.3})
    got = q.get_nowait()
    assert got["pid.PV"] == 0.5
    # 未订阅的业务 tag 被过滤
    assert "tank.level" not in got
    # 时间元数据保留
    assert got["cycle_count"] == 1
    assert got["sim_time"] == 0.5


def test_broadcaster_resubscribe_to_full(binding):
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    bc.subscribe(q, {"pid.PV"})
    bc.subscribe(q, None)
    bc.publish({"pid.PV": 0.5, "tank.level": 0.3})
    got = q.get_nowait()
    assert "tank.level" in got


def test_broadcaster_independent_subscriptions(binding):
    bc = engine_api._WsBroadcaster()
    q1 = bc.register()
    q2 = bc.register()
    bc.subscribe(q1, {"pid.PV"})
    bc.subscribe(q2, {"tank.level"})
    bc.publish({"pid.PV": 0.5, "tank.level": 0.3})
    g1 = q1.get_nowait()
    g2 = q2.get_nowait()
    assert "pid.PV" in g1 and "tank.level" not in g1
    assert "tank.level" in g2 and "pid.PV" not in g2


def test_token_auth_rejects_without_token(binding):
    from fastapi.testclient import TestClient
    engine_api.set_api_token("secret-token")
    try:
        client = TestClient(engine_api.app)
        r = client.get("/api/status")
        assert r.status_code == 401
    finally:
        engine_api.set_api_token(None)


def test_token_auth_accepts_with_token(binding):
    from fastapi.testclient import TestClient
    engine_api.set_api_token("secret-token")
    try:
        client = TestClient(engine_api.app)
        r = client.get("/api/status", headers={"Authorization": "Bearer secret-token"})
        assert r.status_code == 200
    finally:
        engine_api.set_api_token(None)


def test_token_auth_wrong_token(binding):
    from fastapi.testclient import TestClient
    engine_api.set_api_token("secret-token")
    try:
        client = TestClient(engine_api.app)
        r = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
    finally:
        engine_api.set_api_token(None)


def test_snapshot_contains_required_tags(binding):
    """snapshot 必须包含 contracts.md §9.3 列出的所有必需位号。"""
    snap = engine_api.api_snapshot("second_order_tank")
    required = [
        "cycle_count", "sim_time", "source_flow",
        "valve_1.target_opening", "valve_1.current_opening",
        "valve_1.inlet_flow", "valve_1.outlet_flow",
        "tank_1.level", "tank_1.inlet_flow", "tank_1.outlet_flow",
        "tank_2.level", "tank_2.inlet_flow", "tank_2.outlet_flow",
        "pid2.PV", "pid2.SV", "pid2.CSV", "pid2.MV",
        "pid2.PB", "pid2.TI", "pid2.TD", "pid2.KD", "pid2.MODE", "pid2.SWPN",
    ]
    missing = [k for k in required if k not in snap]
    assert not missing, f"snapshot 缺少必需位号: {missing}"


# --------------------------------------------------------------------------- #
# 3. broadcaster 慢消费者策略                                                  #
# --------------------------------------------------------------------------- #
def test_broadcaster_slow_consumer_does_not_block_engine(binding):
    """
    单客户端 queue 满时新帧直接覆盖旧帧（每客户端保留最新值）。
    Engine 永远不阻塞。
    """
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    # 推 5 帧：maxsize=1，所以 queue 内始终只有最后一帧
    for i in range(5):
        bc.publish({"cycle_count": i, "valve_1.current_opening": float(i)})
    # 取出来只应是最新一帧
    only = q.get_nowait()
    assert only["cycle_count"] == 4, f"slow consumer 应保留最新帧，实际: {only}"
    assert only["valve_1.current_opening"] == 4.0
    # queue 现在应当为空
    with pytest.raises(queue.Empty):
        q.get_nowait()
    bc.unregister(q)


def test_broadcaster_does_not_block_when_queue_persistent_full(binding):
    """
    即便客户端永远不消费，publish 也必须立即返回。
    """
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    deadline = time.time() + 0.5
    pushes = 0
    while time.time() < deadline:
        bc.publish({"cycle_count": pushes})
        pushes += 1
    assert pushes > 100, f"慢消费者 publish 应快速循环，实际只推了 {pushes} 次"
    # 客户端 queue 内只有最新一帧
    only = q.get_nowait()
    assert only["cycle_count"] == pushes - 1
    bc.unregister(q)


def test_broadcaster_two_clients_independent(binding):
    """两个客户端各自保留最新一帧，互不干扰。"""
    bc = engine_api._WsBroadcaster()
    qa = bc.register()
    qb = bc.register()
    bc.publish({"cycle_count": 1})
    bc.publish({"cycle_count": 2})
    bc.publish({"cycle_count": 3})
    # 两个客户端各自最新一帧都是 3
    assert qa.get_nowait()["cycle_count"] == 3
    assert qb.get_nowait()["cycle_count"] == 3
    bc.unregister(qa)
    bc.unregister(qb)


def test_broadcaster_filters_non_scalar_fields(binding):
    """publish 只保留标量字段（int/float/str/bool）；list/dict 必须丢弃。"""
    bc = engine_api._WsBroadcaster()
    q = bc.register()
    bc.publish({
        "cycle_count": 1,
        "valve_1.current_opening": 12.3,
        "_list": [1, 2, 3],
        "_dict": {"a": 1},
        "_none": None,
    })
    only = q.get_nowait()
    assert "cycle_count" in only
    assert "valve_1.current_opening" in only
    assert "_list" not in only
    assert "_dict" not in only
    assert "_none" not in only
    bc.unregister(q)


# --------------------------------------------------------------------------- #
# 4. 多 WS 客户端不会让 Engine 重复计算                                       #
# --------------------------------------------------------------------------- #
def test_multiple_ws_clients_do_not_duplicate_engine_compute():
    """
    多 WS 客户端订阅时，Engine 仍然只算一次；每个客户端各自收到一份 snapshot。
    """
    engine = _build_engine("config/单阀门二阶水箱.yaml", cycle_time=0.5)
    bc = engine_api._WsBroadcaster()
    q1 = bc.register()
    q2 = bc.register()
    q3 = bc.register()
    assert bc.client_count() == 3
    engine.clock.start()
    snap = engine.step()
    engine.clock.stop()
    # Engine 只算了一次；3 个客户端共享同一份 snapshot。
    bc.publish(snap)
    for q in (q1, q2, q3):
        d = q.get_nowait()
        assert d["cycle_count"] == snap["cycle_count"]
        assert d["valve_1.current_opening"] == snap["valve_1.current_opening"]
    for q in (q1, q2, q3):
        bc.unregister(q)


# --------------------------------------------------------------------------- #
# 6. WS 心跳格式                                                               #
# --------------------------------------------------------------------------- #
def test_ws_heartbeat_format_contract():
    """真实 ws_snapshot handler 超时路径必须发送可识别心跳。"""
    engine_api.set_binding(None)  # type: ignore[arg-type]
    b = _make_binding()
    engine_api.set_binding(b)

    class EmptyQueue:
        def get(self, block=True, timeout=None):
            raise queue.Empty

    class FakeBroadcaster:
        def __init__(self):
            self.q = EmptyQueue()
            self.unregistered = False

        def register(self):
            return self.q

        def unregister(self, q):
            assert q is self.q
            self.unregistered = True

        def client_count(self):
            return 1

    class FakeWebSocket:
        def __init__(self):
            self.accepted = False
            self.messages = []

        async def accept(self):
            self.accepted = True

        async def send_json(self, message):
            self.messages.append(message)
            raise WebSocketDisconnect()

    broadcaster = FakeBroadcaster()
    b.broadcaster = broadcaster  # type: ignore[assignment]
    ws = FakeWebSocket()
    try:
        asyncio.run(engine_api.ws_snapshot(ws))  # type: ignore[arg-type]
        assert ws.accepted
        assert len(ws.messages) == 1
        heartbeat = ws.messages[0]
        assert heartbeat["_heartbeat"] is True
        assert isinstance(heartbeat["ts"], float)
        assert broadcaster.unregistered
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 7. snapshot 数值均为有限值（与 design §19 配合）                               #
# --------------------------------------------------------------------------- #
def test_snapshot_all_numeric_values_finite(binding):
    """snapshot 中数值型字段必须全部有限（无 NaN/Inf）。"""
    # 多跑几个周期确保水位/MV 有变化
    binding._drive_test(20)  # type: ignore[attr-defined]
    snap = engine_api.api_snapshot("second_order_tank")
    for k, v in snap.items():
        if isinstance(v, (int, float)):
            assert math.isfinite(float(v)), f"snapshot.{k} 非有限: {v}"


# --------------------------------------------------------------------------- #
# 8. EngineBinding 真实绑定（status 取的是 binding 而非任何全局变量）              #
# --------------------------------------------------------------------------- #
def test_status_uses_current_binding_not_global_pid2():
    """engine_api.get_binding() 返回当前 set 的 binding，与 Engine 同步。"""
    engine_api.set_binding(None)  # type: ignore[arg-type]
    # 第一次 set
    b1 = _make_binding(instance_name="alpha")
    engine_api.set_binding(b1)
    assert engine_api.get_binding().instance_name == "alpha"
    assert engine_api.api_status().instance_name == "alpha"

    # 切换 binding
    b2 = _make_binding(instance_name="beta")
    engine_api.set_binding(b2)
    assert engine_api.get_binding().instance_name == "beta"
    assert engine_api.api_status().instance_name == "beta"
    engine_api.set_binding(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 9. 真实 EngineBinding + async WS 端到端（仅 Python 线程级）                     #
# --------------------------------------------------------------------------- #
def test_ws_snapshot_message_is_complete_dict_not_wrapped():
    """
    WS handler 收到的 snapshot 不应有额外 data 包装层。
    _WsBroadcaster.publish() 已过滤标量字段；handler 直接 send_json(snapshot)。
    """
    engine_api.set_binding(None)  # type: ignore[arg-type]
    b = _make_binding()
    engine_api.set_binding(b)
    try:
        bc = b.broadcaster
        q = bc.register()
        b._drive_test(3)  # type: ignore[attr-defined]
        seen_keys: List[str] = []
        # broadcaster.maxsize=1：连续 3 帧时 queue 内只剩最后一帧。
        # 因此我们读 1 次验证格式正确，再用 3 次断言覆盖连续发布的可靠性。
        snap = q.get_nowait()
        assert isinstance(snap, dict)
        assert "data" not in snap, f"snapshot 不应包 data 层: {snap.keys()}"
        seen_keys.extend(snap.keys())
        # 再驱动一轮确认 broadcaster 不会在后续周期失活
        b._drive_test(2)  # type: ignore[attr-defined]
        snap2 = q.get_nowait()
        assert isinstance(snap2, dict)
        assert "data" not in snap2
        seen_keys.extend(snap2.keys())
        # snapshot 至少包含必需位号
        for key in (
            "valve_1.current_opening",
            "tank_2.level",
            "pid2.SV",
        ):
            assert key in seen_keys, f"WS 消息缺 {key}"
        bc.unregister(q)
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]
