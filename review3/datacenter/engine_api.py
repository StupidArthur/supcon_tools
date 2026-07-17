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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from components.utils.logger import get_logger


logger = get_logger("engine_api")


# --------------------------------------------------------------------------- #
# 数据模型（HTTP 请求/响应）                                                  #
# --------------------------------------------------------------------------- #

class ParamUpdateRequest(BaseModel):
    param: str = Field(..., description="参数名，如 PB / TI / SV")
    value: float = Field(..., description="新值")


class OverrideRequest(BaseModel):
    tag: str = Field(..., description="位号名（变量名或 instance.attribute）")
    value: float = Field(..., description="新值")


class ExportRequest(BaseModel):
    path: str = Field(..., description="CSV 输出路径")
    cycles: Optional[int] = Field(default=None, description="导出最近 N 个 cycle；None=导出全部缓冲")


class StatusResponse(BaseModel):
    instance_name: str
    mode: str
    cycle_count: int
    sim_time: float
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

    慢消费者策略：队列上限 200 条；新数据到来时若队列已满则丢弃最旧条目，
    保证 WS 客户端不会反过来拖慢引擎线程。
    """

    _MAX_QUEUE = 200

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
            # 队列满时 put 会丢最旧的（maxlen 已设）
            try:
                q.put_nowait(safe)
            except queue.Full:
                # 极端情况下满且 race 丢失，直接跳过本客户端这一帧
                pass


# --------------------------------------------------------------------------- #
# 引擎绑定（由 standalone_main 在启动时注入）                                  #
# --------------------------------------------------------------------------- #

@dataclass
class EngineBinding:
    """
    把 DataFactory Engine 实例 + shared_data + 实例名绑定到 FastAPI app。

    snapshot_buffer：引擎线程可选地把每周期 snapshot 追加到这里，用于 export。
    """

    instance_name: str
    engine: Any
    shared_data: Dict[str, float]
    snapshot_buffer: List[Dict[str, Any]] = field(default_factory=list)
    _buffer_lock: threading.Lock = field(default_factory=threading.Lock)
    _buffer_max: int = 10000  # 最多保留最近 10000 个周期
    broadcaster: _WsBroadcaster = field(default_factory=_WsBroadcaster)

    def push_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """由 standalone_main 的引擎线程每周期调用一次。"""
        # WS 广播
        self.broadcaster.publish(snapshot)
        # 环形缓冲（保留最近 N 个周期供 export）
        with self._buffer_lock:
            self.snapshot_buffer.append(snapshot)
            if len(self.snapshot_buffer) > self._buffer_max:
                # 砍掉前 1/4
                del self.snapshot_buffer[: self._buffer_max // 4]

    def get_recent_snapshots(self, n: Optional[int]) -> List[Dict[str, Any]]:
        with self._buffer_lock:
            buf = list(self.snapshot_buffer)
        if n is not None and n > 0 and n < len(buf):
            return buf[-n:]
        return buf


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
    """实例运行状态。"""
    b = get_binding()
    stats = b.engine.get_statistics()
    snapshot = b.shared_data  # 引擎线程每周期写入的 dict
    return StatusResponse(
        instance_name=b.instance_name,
        mode=str(stats.get("mode", "UNKNOWN")),
        cycle_count=int(snapshot.get("cycle_count", 0)),
        sim_time=float(snapshot.get("sim_time", 0.0)),
        safe_state=bool(snapshot.get("_safe_state", False)),
        consecutive_failures=int(snapshot.get("_consecutive_failures", 0)),
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


@app.get("/api/instances/{name}/snapshot")
def api_snapshot(name: str) -> Dict[str, Any]:
    """最新一次 snapshot。"""
    b = get_binding()
    if name != b.instance_name:
        raise HTTPException(status_code=404, detail=f"实例不存在: {name}")
    return dict(b.shared_data)


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
# WebSocket                                                                   #
# --------------------------------------------------------------------------- #

@app.websocket("/ws/snapshot")
async def ws_snapshot(ws: WebSocket) -> None:
    """
    每周期推一次 snapshot。

    引擎线程把 snapshot put 到 broadcaster queue；这里 await 阻塞拿数据再发给客户端。
    断开时 unregister。
    """
    await ws.accept()
    b = get_binding()
    my_queue = b.broadcaster.register()
    logger.info("WS client connected, total clients=%d",
                len(b.broadcaster._clients))
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