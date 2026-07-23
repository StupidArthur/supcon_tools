"""
FastAPI HTTP + WebSocket 接口，用于 Wails GUI 调试工具。

- HTTP REST：状态、meta、snapshot、调参、覆写、CSV 导出
- WebSocket：每周期推送一次 snapshot（由引擎线程主动 put 到 ws_queue）

MVP 单实例：API 路径保留 {name} 但只支持一个 Engine。
"""

from __future__ import annotations

import asyncio
import csv
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from components.utils.logger import get_logger
from controller.engine import AtomicWrite


logger = get_logger("engine_api")

_WRITE_CONFIRM_ABS_TOL = 1e-6
_DEFAULT_CONFIRM_TIMEOUT_S = 3.0


# --------------------------------------------------------------------------- #
# 数据模型（HTTP 请求/响应）                                                  #
# --------------------------------------------------------------------------- #

class ParamUpdateRequest(BaseModel):
    param: str = Field(..., description="参数名，如 PB / TI / SV")
    value: float = Field(..., description="新值")


class OverrideRequest(BaseModel):
    tag: str = Field(..., description="位号名（变量名或 instance.attribute）")
    value: float = Field(..., description="新值")


class AtomicWriteItem(BaseModel):
    tag: str
    value: float


class AtomicWritesRequest(BaseModel):
    writes: List[AtomicWriteItem]
    confirm_timeout_s: Optional[float] = None


class ExportRequest(BaseModel):
    path: str = Field(..., description="CSV 输出路径")
    cycles: Optional[int] = Field(default=None, description="导出最近 N 个 cycle；None=导出全部缓冲")


@dataclass
class WriteBatchRecord:
    batch_id: str
    writes: List[Dict[str, Any]]
    status: str
    accepted_cycle_count: Optional[int]
    confirmed_cycle_count: Optional[int]
    accepted_monotonic: float
    confirm_timeout_s: float
    error: Optional[str] = None


class StatusResponse(BaseModel):
    instance_name: str
    mode: str
    cycle_count: int
    sim_time: float
    cycle_time: float
    safe_state: bool
    consecutive_failures: int


# --------------------------------------------------------------------------- #
# WS 客户端连接管理                                                           #
# --------------------------------------------------------------------------- #

class _WsBroadcaster:
    """
    把引擎每周期写入的 snapshot 广播给所有 WS 客户端。

    引擎线程调用 ``publish(snapshot)``；WebSocket handler 协程从自己的
    queue 里 ``get()`` 拿数据推给浏览器。

    慢消费者策略：
    - 每客户端 queue.Queue(maxsize=1)：始终只保留最新一帧。
    - 新帧到达时若旧帧未消费，直接丢弃旧帧（get_nowait 后 put_nowait）。
    - publish 对每个客户端均严格非阻塞，永远不会拖慢引擎线程。
    - 多 WS 客户端不会触发 Engine 重复计算：snapshot 只来自 Engine 单线程。
    """

    _MAX_QUEUE = 1

    def __init__(self) -> None:
        self._clients: Set["queue.Queue[Dict[str, Any]]"] = set()
        self._lock = threading.Lock()

    def register(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=self._MAX_QUEUE)
        with self._lock:
            self._clients.add(q)
        return q

    def unregister(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            self._clients.discard(q)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def publish(self, snapshot: Dict[str, Any]) -> None:
        # 在引擎线程里调用，snapshot 已经是 dict 拷贝，这里直接转 JSON-safe dict
        # 简单数据：只保留标量；过滤掉 None / dict / list 等非标量值
        safe: Dict[str, Any] = {}
        for k, v in snapshot.items():
            if isinstance(v, (int, float, str, bool)):
                safe[k] = v
        with self._lock:
            queues = list(self._clients)
        for q in queues:
            # 始终只保留最新一帧；旧帧未消费则丢弃。
            try:
                # 非阻塞尝试取出已有条目（不阻塞 Engine）
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
            except Exception:
                pass
            try:
                q.put_nowait(safe)
            except queue.Full:
                # 极端 race：仍满则直接丢弃新帧，本客户端短暂缺帧不影响 Engine。
                pass


# --------------------------------------------------------------------------- #
# 引擎绑定（由 standalone_main 在启动时注入）                                  #
# --------------------------------------------------------------------------- #

@dataclass
class EngineBinding:
    """
    把 DataFactory Engine 实例 + shared_data + 实例名绑定到 FastAPI app。

    关键契约：
      - ``_latest_snapshot`` 是 Engine 线程最近一次推送的完整 snapshot。
      - 在 ``_latest_snapshot_lock`` 锁内写入；status 和 /snapshot 必须从同一份读取，
        保证 cycle_count/sim_time 与真实 Engine 推进一致。
      - ``snapshot_buffer`` 保留最近 N 个周期供 export。
      - ``_batches`` 维护原子写 pending/applied/failed 生命周期。
    """

    instance_name: str
    engine: Any
    shared_data: Dict[str, float]
    snapshot_buffer: List[Dict[str, Any]] = field(default_factory=list)
    _buffer_lock: threading.Lock = field(default_factory=threading.Lock)
    _buffer_max: int = 10000  # 最多保留最近 10000 个周期
    broadcaster: _WsBroadcaster = field(default_factory=_WsBroadcaster)

    # 最近一份完整 snapshot（含 cycle_count / sim_time 等元数据）。
    # 阶段 4 要求：status 和 REST snapshot 必须在同一份 snapshot 上读取；
    # 任何缺字段（含 cycle_count / sim_time）必须显式缺失，不替换为 0。
    _latest_snapshot: Optional[Dict[str, Any]] = None
    _latest_snapshot_lock: threading.Lock = field(default_factory=threading.Lock)
    _batch_lock: threading.Lock = field(default_factory=threading.Lock)
    _batches: Dict[str, WriteBatchRecord] = field(default_factory=dict)
    force_manager: Any = None

    def push_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """由 standalone_main 的引擎线程每周期调用一次。

        写入顺序：先替换 _latest_snapshot（供 REST / status 使用），再广播 WS；
        status 与 /snapshot 看到的 cycle_count/sim_time 必然等于最新引擎周期。
        """
        # 1) 锁内保存最近一份完整 snapshot（深拷贝避免 Engine 线程复写）
        with self._latest_snapshot_lock:
            self._latest_snapshot = {k: v for k, v in snapshot.items()}

        # 2) WS 广播（标量过滤在 broadcaster 内完成）
        self.broadcaster.publish(snapshot)

        # 3) 环形缓冲（保留最近 N 个周期供 export）
        with self._buffer_lock:
            self.snapshot_buffer.append(snapshot)
            if len(self.snapshot_buffer) > self._buffer_max:
                # 砍掉前 1/4
                del self.snapshot_buffer[: self._buffer_max // 4]

        # 4) 原子写 batch 确认 / 超时
        self._update_write_batches(snapshot)

    def get_recent_snapshots(self, n: Optional[int]) -> List[Dict[str, Any]]:
        with self._buffer_lock:
            buf = list(self.snapshot_buffer)
        if n is not None and n > 0 and n < len(buf):
            return buf[-n:]
        return buf

    # 返回最近一份完整 snapshot 的浅拷贝（dict 顶层）。若 Engine 尚未推过任何
    # 周期则返回 None——调用方必须显式判定，不能用 0 / NaN 冒充。
    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        with self._latest_snapshot_lock:
            if self._latest_snapshot is None:
                return None
            return dict(self._latest_snapshot)

    def submit_atomic_writes(
        self,
        writes: List[Dict[str, Any]],
        confirm_timeout_s: Optional[float] = None,
    ) -> WriteBatchRecord:
        timeout = (
            float(confirm_timeout_s)
            if confirm_timeout_s is not None
            else _DEFAULT_CONFIRM_TIMEOUT_S
        )
        if not (timeout > 0) or timeout != timeout or timeout == float("inf"):
            raise ValueError("confirm_timeout_s must be a finite positive number")
        atomic_items = [
            AtomicWrite(tag=str(w["tag"]), value=float(w["value"])) for w in writes
        ]
        self.engine.queue_atomic_writes(atomic_items)
        snap = self.get_latest_snapshot() or {}
        accepted_cycle = snap.get("cycle_count")
        batch_id = str(uuid4())
        record = WriteBatchRecord(
            batch_id=batch_id,
            writes=[{"tag": w.tag, "value": w.value} for w in atomic_items],
            status="pending",
            accepted_cycle_count=accepted_cycle if isinstance(accepted_cycle, int) else None,
            confirmed_cycle_count=None,
            accepted_monotonic=time.monotonic(),
            confirm_timeout_s=timeout,
            error=None,
        )
        with self._batch_lock:
            self._batches[batch_id] = record
        return record

    def get_batch(self, batch_id: str) -> Optional[WriteBatchRecord]:
        with self._batch_lock:
            rec = self._batches.get(batch_id)
            if rec is None:
                return None
            self._expire_if_needed(rec, time.monotonic())
            return rec

    def list_batches(self) -> List[WriteBatchRecord]:
        now = time.monotonic()
        with self._batch_lock:
            for rec in self._batches.values():
                self._expire_if_needed(rec, now)
            return list(self._batches.values())

    def _expire_if_needed(self, rec: WriteBatchRecord, now: float) -> None:
        if rec.status != "pending":
            return
        if now - rec.accepted_monotonic >= rec.confirm_timeout_s:
            rec.status = "failed"
            rec.error = "confirm_timeout"

    def _update_write_batches(self, snapshot: Dict[str, Any]) -> None:
        now = time.monotonic()
        cycle = snapshot.get("cycle_count")
        with self._batch_lock:
            for rec in self._batches.values():
                if rec.status != "pending":
                    continue
                self._expire_if_needed(rec, now)
                if rec.status != "pending":
                    continue
                if self._batch_fully_matched(rec, snapshot):
                    rec.status = "applied"
                    rec.confirmed_cycle_count = cycle if isinstance(cycle, int) else None
                    rec.error = None

    @staticmethod
    def _batch_fully_matched(rec: WriteBatchRecord, snapshot: Dict[str, Any]) -> bool:
        for item in rec.writes:
            tag = item["tag"]
            expected = float(item["value"])
            if tag not in snapshot:
                return False
            try:
                actual_f = float(snapshot[tag])
            except (TypeError, ValueError):
                return False
            if abs(actual_f - expected) > _WRITE_CONFIRM_ABS_TOL:
                return False
        return True


# --------------------------------------------------------------------------- #
# FastAPI app                                                                 #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="DataFactory Debug API",
    description="Wails GUI 调试工具的 HTTP + WebSocket 接口",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局 binding 引用（由 set_binding() 注入）
_binding: Optional[EngineBinding] = None
_binding_lock = threading.Lock()


def set_binding(binding: EngineBinding) -> None:
    """由 standalone_main 在启动时调用，把 Engine 绑到全局。"""
    global _binding
    with _binding_lock:
        _binding = binding


def get_binding() -> EngineBinding:
    with _binding_lock:
        if _binding is None:
            raise HTTPException(status_code=503, detail="Engine 未就绪")
        return _binding


# --------------------------------------------------------------------------- #
# HTTP 路由                                                                   #
# --------------------------------------------------------------------------- #

@app.get("/api/status", response_model=StatusResponse)
def api_status() -> StatusResponse:
    """实例运行状态。

    ``instance_name`` 来自 ``EngineBinding.instance_name``（由 ``--name`` 指定），
    与 Program 实例名（pid2 / tank_2 等）不是同一个命名空间。
    前端必须用此字段的真实值再调用 ``/api/instances/{instance_name}/...``。

    ``cycle_count`` / ``sim_time`` 与 ``/snapshot`` 来自同一份最近完整 snapshot：
    EngineBinding 在锁内保存，REST / status 一致读取，绝不通过 engine.clock
    二次推断，避免和 snapshot 出现分叉。
    """
    b = get_binding()
    stats = b.engine.get_statistics()
    latest = b.get_latest_snapshot()  # 与 /snapshot 同源
    cycle_count = int(latest["cycle_count"]) if latest and "cycle_count" in latest else 0
    sim_time = float(latest["sim_time"]) if latest and "sim_time" in latest else 0.0
    safe_state = bool(latest.get("_safe_state", False)) if latest else False
    consecutive_failures = (
        int(latest.get("_consecutive_failures", 0)) if latest else 0
    )
    cycle_time = float(getattr(b.engine.clock.config, "cycle_time", 0.5) or 0.5)
    return StatusResponse(
        instance_name=b.instance_name,
        mode=str(stats.get("mode", "UNKNOWN")),
        cycle_count=cycle_count,
        sim_time=sim_time,
        cycle_time=cycle_time,
        safe_state=safe_state,
        consecutive_failures=consecutive_failures,
    )


@app.get("/api/instances/{name}/meta")
def api_meta(name: str) -> Dict[str, Any]:
    """所有 program 项的 stored_attributes + default_params + param_descriptions。"""
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")
    return {
        "instance_name": b.instance_name,
        "meta": b.engine.get_variable_meta(),
        "statistics": b.engine.get_statistics(),
    }


# 运行元数据键：不作为业务 tag 暴露给通用画面/趋势。
_RUNTIME_META_KEYS = {
    "cycle_count", "sim_time", "exec_ratio", "need_sample", "time_str",
    "_safe_state", "_consecutive_failures",
}


@app.get("/api/instances/{name}/tags")
def api_tags(name: str) -> Dict[str, Any]:
    """通用 tag catalog：名称来自真实运行 meta，forceable 来自 shared_data 数值键。

    - 不把 cycle_count/sim_time 等运行元数据当业务 tag；
    - metadata 缺失仍返回 tag，描述为空；
    - 排序稳定；
    - 不从名称后缀推断类型或权限。
    """
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")

    meta = b.engine.get_variable_meta() or {}
    forceable = {k for k, v in b.shared_data.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)}

    tags = []
    for tag in sorted(meta.keys()):
        if tag in _RUNTIME_META_KEYS or tag.startswith("_"):
            continue
        m = meta[tag]
        value = b.shared_data.get(tag)
        data_type = "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "unknown"
        tags.append({
            "name": tag,
            "dataType": data_type,
            "description": m.get("description", "") or "",
            "instance": m.get("instance", "") or "",
            "attribute": m.get("param", "") or "",
            "writable": True,
            "forceable": tag in forceable,
            "display": bool(m.get("is_display", False)),
            "plotScaleRef": m.get("plot_scale_ref"),
        })
    return {"ok": True, "tags": tags}


@app.get("/api/instances/{name}/snapshot")
def api_snapshot(name: str) -> Dict[str, Any]:
    """最新一次 snapshot。

    与 ``/api/status`` 同源：均读取 EngineBinding._latest_snapshot（锁内替换）。
    snapshot 缺失的字段（如 cycle_count/sim_time 未推送过）原样缺失，绝不替换为 0。
    """
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")
    latest = b.get_latest_snapshot()
    if latest is None:
        # 引擎尚未推过任何周期；返回空 dict 让前端明确知道"无 snapshot"。
        return {}
    return latest


@app.post("/api/instances/{name}/params")
def api_set_param(name: str, req: ParamUpdateRequest) -> Dict[str, Any]:
    """
    改算法参数。

    body: ``{"param": "PB", "value": 15.0}``

    注意：只能改 instance 上的属性（PB/TI/TD 等）。要改 VARIABLE 类型用 /override。
    """
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")
    b.engine.queue_param_update(name, req.param, req.value)
    return {"ok": True, "queued": {"instance": name, "param": req.param, "value": req.value}}


@app.post("/api/instances/{name}/override")
def api_override(name: str, req: OverrideRequest) -> Dict[str, Any]:
    """
    覆写位号值（VARIABLE 或 instance.attribute）。

    body: ``{"tag": "v_name.SV", "value": 1.5}``
    """
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")
    b.engine.override_variable(req.tag, req.value)
    return {"ok": True, "queued": {"tag": req.tag, "value": req.value}}


def _batch_to_dict(rec: WriteBatchRecord) -> Dict[str, Any]:
    return {
        "ok": True,
        "batch_id": rec.batch_id,
        "status": rec.status,
        "writes": rec.writes,
        "accepted_cycle_count": rec.accepted_cycle_count,
        "confirmed_cycle_count": rec.confirmed_cycle_count,
        "error": rec.error,
    }


@app.post("/api/instances/{runtimeName}/writes")
def api_atomic_writes(runtimeName: str, req: AtomicWritesRequest) -> Dict[str, Any]:
    """原子在线写：整批校验入队，成功仅返回 pending。"""
    b = get_binding()
    if runtimeName != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {runtimeName}")
    if not req.writes:
        raise HTTPException(status_code=400, detail="writes must not be empty")
    try:
        record = b.submit_atomic_writes(
            [{"tag": w.tag, "value": w.value} for w in req.writes],
            confirm_timeout_s=req.confirm_timeout_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"atomic write rejected: {exc}") from exc
    return {
        "ok": True,
        "batch_id": record.batch_id,
        "status": "pending",
        "writes": record.writes,
        "accepted_cycle_count": record.accepted_cycle_count,
    }


@app.get("/api/instances/{runtimeName}/writes")
def api_list_writes(runtimeName: str) -> Dict[str, Any]:
    b = get_binding()
    if runtimeName != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {runtimeName}")
    batches = [_batch_to_dict(rec) for rec in b.list_batches()]
    return {"ok": True, "batches": batches}


@app.get("/api/instances/{runtimeName}/writes/{batchId}")
def api_get_write_batch(runtimeName: str, batchId: str) -> Dict[str, Any]:
    b = get_binding()
    if runtimeName != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {runtimeName}")
    rec = b.get_batch(batchId)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"batch 不存在: {batchId}")
    return _batch_to_dict(rec)


@app.post("/api/instances/{name}/export")
def api_export(name: str, req: ExportRequest) -> Dict[str, Any]:
    """导出最近 N 个 cycle 的 snapshot 到 CSV。"""
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")

    snapshots = b.get_recent_snapshots(req.cycles)
    if not snapshots:
        raise HTTPException(status_code=400, detail="没有可导出的快照")

    # 汇总 keys，过滤元数据
    exclude = {"cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio",
               "_safe_state", "_consecutive_failures"}
    keys: Set[str] = set()
    for s in snapshots:
        keys.update(s.keys())
    export_keys = sorted(k for k in keys if k not in exclude)

    output_path = Path(req.path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=export_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(snapshots)

    return {
        "ok": True,
        "path": str(output_path),
        "rows": len(snapshots),
        "columns": len(export_keys),
    }


# --------------------------------------------------------------------------- #
# 输出强制                                                                     #
# --------------------------------------------------------------------------- #

class ForceSetRequest(BaseModel):
    tag: str
    mode: str = Field(..., description="follow | hold | zero | fixed")
    value: Optional[float] = None
    duration: Optional[float] = Field(default=None, description="持续时间（秒），到期自动恢复 follow")


def _refresh_valid_tags(b: "EngineBinding") -> None:
    """从 shared_data（实际发布到 UA 的数值键）建立权威可强制位号集合。"""
    if b.force_manager is None:
        return
    tags = {k for k, v in b.shared_data.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}
    b.force_manager.set_valid_tags(tags)


@app.post("/api/force")
def api_force_set(req: ForceSetRequest) -> Dict[str, Any]:
    from datacenter.force_manager import ForceError
    b = get_binding()
    if b.force_manager is None:
        raise HTTPException(status_code=503, detail="强制层未启用")
    _refresh_valid_tags(b)
    try:
        entry = b.force_manager.set_force(req.tag, req.mode, req.value, req.duration)
    except ForceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "tag": req.tag, "force": entry}


@app.delete("/api/force/{tag}")
def api_force_clear(tag: str) -> Dict[str, Any]:
    b = get_binding()
    if b.force_manager is None:
        raise HTTPException(status_code=503, detail="强制层未启用")
    b.force_manager.clear_force(tag)
    return {"ok": True, "tag": tag}


@app.delete("/api/force")
def api_force_clear_all() -> Dict[str, Any]:
    b = get_binding()
    if b.force_manager is None:
        raise HTTPException(status_code=503, detail="强制层未启用")
    b.force_manager.clear_all()
    return {"ok": True}


@app.get("/api/force")
def api_force_list() -> Dict[str, Any]:
    b = get_binding()
    _refresh_valid_tags(b)
    if b.force_manager is None:
        return {"ok": True, "forces": {}, "tags": []}
    tags = sorted(b.force_manager.snapshot_valid_tags())
    return {"ok": True, "forces": b.force_manager.snapshot(), "tags": tags}


# --------------------------------------------------------------------------- #
# WebSocket                                                                   #
# --------------------------------------------------------------------------- #

@app.websocket("/ws/snapshot")
async def ws_snapshot(ws: WebSocket) -> None:
    """
    每周期推一次 snapshot。

    引擎线程把 snapshot put 到 broadcaster queue；这里 await 阻塞拿数据再发给客户端。
    断开时 unregister。

    心跳：1s 内未收到真实 snapshot，发送 ``{"_heartbeat": true, "ts": ...}``。
    真实 snapshot 本身就是完整 dict，不再包一层 ``data``。
    """
    await ws.accept()
    b = get_binding()
    my_queue = b.broadcaster.register()
    logger.info("WS client connected, total clients=%d",
                b.broadcaster.client_count())
    try:
        while True:
            # 从队列取 snapshot。run_in_executor 把阻塞 get 放到线程池，避免阻塞 asyncio loop。
            loop = asyncio.get_running_loop()
            try:
                snapshot = await loop.run_in_executor(None, my_queue.get, True, 1.0)
            except queue.Empty:
                # 1s 内没数据，发送心跳（保持连接活跃 + 前端可识别"还活着"）
                await ws.send_json({"_heartbeat": True, "ts": time.time()})
                continue
            # snapshot 本身就是完整对象，不读取 message.data，也不额外包装。
            await ws.send_json(snapshot)
    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    except Exception as e:
        logger.error("WS error: %s", e, exc_info=True)
    finally:
        b.broadcaster.unregister(my_queue)


# --------------------------------------------------------------------------- #
# uvicorn 启动入口                                                            #
# --------------------------------------------------------------------------- #

def run_api_server(binding: EngineBinding, host: str, port: int) -> threading.Thread:
    """
    在新线程里启动 uvicorn + FastAPI。

    Returns: daemon 线程句柄，调用方可 join。
    """
    set_binding(binding)

    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        try:
            server.run()
        except Exception as e:
            logger.error("uvicorn crashed: %s", e, exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name="FastAPI-Thread")
    thread.start()
    logger.info("FastAPI server started on http://%s:%d", host, port)
    return thread