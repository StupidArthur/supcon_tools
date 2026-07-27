"""
FastAPI HTTP + WebSocket 接口，用于 Wails GUI 调试工具。

- HTTP REST：状态、meta、snapshot、调参、覆写、CSV 导出
- WebSocket：每周期推送一次 snapshot（由引擎线程主动 put 到 ws_queue）

MVP 单实例：API 路径保留 {name} 但只支持一个 Engine。
"""

from __future__ import annotations

import asyncio
import csv
import os
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
    MAX_SUBSCRIPTIONS = 5000

    def __init__(self) -> None:
        # queue -> 订阅 tag 集合（None 表示全量，向后兼容旧客户端）
        self._clients: Dict["queue.Queue[Dict[str, Any]]", Optional[Set[str]]] = {}
        self._lock = threading.Lock()

    def register(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=self._MAX_QUEUE)
        with self._lock:
            self._clients[q] = None
        return q

    def unregister(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            self._clients.pop(q, None)

    def subscribe(self, q: "queue.Queue[Dict[str, Any]]", tags: Optional[Set[str]]) -> None:
        with self._lock:
            if q in self._clients:
                self._clients[q] = tags

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
            clients = list(self._clients.items())
        for q, sub in clients:
            if sub is None:
                payload = safe
            else:
                # 订阅客户端只收到订阅 tag（保留 cycle_count/sim_time 元数据供时间轴）
                payload = {k: v for k, v in safe.items()
                           if k in sub or k in ("cycle_count", "sim_time")}
            # 始终只保留最新一帧；旧帧未消费则丢弃。
            try:
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
            except Exception:
                pass
            try:
                q.put_nowait(payload)
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
      - service_state / runtime_state 分离（todo.md §4.2）：
        * service_state: starting/ready/stopping/failed — 后台服务本身
        * runtime_state: stopped/starting/running/stopping/failed — 实时运行 Engine
        * 后台服务 ready 不等于运行中
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
    quality_manager: Any = None
    alarm_manager: Any = None
    archiver: Any = None

    # ---- service / runtime 状态分离（todo.md §4.2）----
    service_state: str = "starting"   # starting/ready/stopping/failed
    runtime_state: str = "stopped"    # stopped/starting/running/stopping/failed
    _state_lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- 工程上下文（todo.md §4.4）----
    project_file: Optional[str] = None
    project_dir: Optional[str] = None
    project_name: Optional[str] = None
    project_validation: Optional[Dict[str, Any]] = None  # 最近一次 inspect 结果

    # ---- 关闭信号（todo.md §4.3 /api/service/shutdown）----
    _shutdown_event: threading.Event = field(default_factory=threading.Event)

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

        # 5) 报警评估（异常不阻塞 Engine 周期）
        if self.alarm_manager is not None:
            try:
                self.alarm_manager.evaluate(snapshot)
            except Exception as e:
                logger.error(f"alarm evaluate error: {e}")

        # 6) 运行归档（异常不阻塞 Engine 周期）
        if self.archiver is not None:
            try:
                st = snapshot.get("sim_time")
                self.archiver.record(snapshot, float(st) if isinstance(st, (int, float)) else None)
            except Exception as e:
                logger.error(f"archive record error: {e}")

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


# 本地 API 会话令牌（阶段 9c）。每次运行生成随机 token，仅在内存中。
# 不写 project，不输出日志，运行结束即失效。
_api_token: Optional[str] = None


def set_api_token(token: Optional[str]) -> None:
    global _api_token
    _api_token = token


def current_api_token() -> Optional[str]:
    """返回当前 API Token（仅 service mode 下使用）。

    todo.md §7.3：Token 不暴露给前端，但服务端模块内部需要访问以清理状态。
    """
    return _api_token


def _auth_disabled() -> bool:
    # 明确的开发测试开关下允许无 token 模式。
    return os.environ.get("DATAFACTORY_NO_AUTH") == "1"


# --------------------------------------------------------------------------- #
# service / runtime 状态辅助（todo.md §4.2）                                     #
# --------------------------------------------------------------------------- #

SERVICE_STATE_STARTING = "starting"
SERVICE_STATE_READY = "ready"
SERVICE_STATE_STOPPING = "stopping"
SERVICE_STATE_FAILED = "failed"

RUNTIME_STATE_STOPPED = "stopped"
RUNTIME_STATE_STARTING = "starting"
RUNTIME_STATE_RUNNING = "running"
RUNTIME_STATE_STOPPING = "stopping"
RUNTIME_STATE_FAILED = "failed"


def set_service_state(b: "EngineBinding", state: str) -> None:
    with b._state_lock:
        b.service_state = state


def set_runtime_state(b: "EngineBinding", state: str) -> None:
    with b._state_lock:
        b.runtime_state = state


def get_states(b: "EngineBinding") -> Dict[str, str]:
    with b._state_lock:
        return {"serviceState": b.service_state, "runtimeState": b.runtime_state}


def request_service_shutdown(b: "EngineBinding") -> None:
    """标记服务请求关闭。uvicorn 主循环应在每次请求后检查该标志。"""
    b._shutdown_event.set()


def shutdown_requested(b: "EngineBinding") -> bool:
    return b._shutdown_event.is_set()


def clear_project_context(b: "EngineBinding") -> None:
    """清空当前工程上下文（不触碰 Engine / force / quality）。"""
    b.project_file = None
    b.project_dir = None
    b.project_name = None
    b.project_validation = None


def set_project_context(
    b: "EngineBinding",
    project_file: str,
    project_name: str,
    validation: Optional[Dict[str, Any]] = None,
) -> None:
    b.project_file = project_file
    b.project_name = project_name
    b.project_dir = os.path.dirname(project_file)
    b.project_validation = validation


def validate_requested_token(req_token: Optional[str]) -> bool:
    """校验请求 Token 是否匹配当前服务 Token（None 表示未启用认证）。"""
    expected = current_api_token()
    if expected is None or expected == "":
        return True
    if req_token is None or req_token == "":
        # Authorization 头里的 Bearer token
        return False
    return req_token == expected


@app.middleware("http")
async def token_auth_middleware(request, call_next):
    if _auth_disabled() or _api_token is None:
        return await call_next(request)
    # WebSocket 升级走 query token（在 ws handler 内校验），此处放行。
    if request.url.path.startswith("/ws/"):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {_api_token}":
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": "未授权"})
    return await call_next(request)


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

    启动窗口期（``b.engine`` 尚未注入）的处理：API 已 listen 但 engine holder
    还没填上，get_statistics / clock 会抛 AttributeError。这里返回合法的"启动中"
    状态而不是 500，让 readiness 探测成功、Go 端完成 launch 事务。
    """
    b = get_binding()
    if b.engine is None:
        return StatusResponse(
            instance_name=b.instance_name,
            mode="STARTING",
            cycle_count=0,
            sim_time=0.0,
            cycle_time=0.5,
            safe_state=False,
            consecutive_failures=0,
        )
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


# --------------------------------------------------------------------------- #
# todo.md §4.3：service / runtime 状态                                           #
# --------------------------------------------------------------------------- #

SERVICE_PROTOCOL_VERSION = 1


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    """服务健康探测（todo.md §4.3）。

    Engine 未启动时也必须返回 200，用于 Go 端服务管理器等待 health 就绪。
    """
    b = get_binding()
    states = get_states(b)
    return {
        "ok": True,
        "protocolVersion": SERVICE_PROTOCOL_VERSION,
        "serviceState": states["serviceState"],
        "runtimeState": states["runtimeState"],
        "instanceName": b.instance_name,
    }


class ShutdownRequest(BaseModel):
    reason: Optional[str] = Field(default="client-request")


@app.post("/api/service/shutdown")
def api_service_shutdown(req: ShutdownRequest) -> Dict[str, Any]:
    """请求后台服务优雅关闭（todo.md §4.3）。

    行为：
      1. 若 Engine 正在运行，先请求 runtime stop；
      2. 标记 service_state = stopping；
      3. 设置 _shutdown_event，uvicorn 主循环在下一次请求后退出。
    """
    b = get_binding()
    # 若 Engine 正在运行，标记 runtime 为 stopping（不直接 stop，
    # 让前端可见过渡状态；uvicorn 退出时由 cleanup 强制回收）
    with b._state_lock:
        if b.runtime_state == RUNTIME_STATE_RUNNING:
            b.runtime_state = RUNTIME_STATE_STOPPING
        b.service_state = SERVICE_STATE_STOPPING
    request_service_shutdown(b)
    logger.info("service shutdown requested: %s", req.reason or "client-request")
    return {"ok": True, "serviceState": b.service_state, "runtimeState": b.runtime_state}


# --------------------------------------------------------------------------- #
# todo.md §4.4：工程上下文同步                                                   #
# --------------------------------------------------------------------------- #

class ProjectOpenRequest(BaseModel):
    projectFile: str = Field(..., description="project.yaml 绝对路径")


class ProjectReloadRequest(BaseModel):
    projectFile: Optional[str] = Field(default=None, description="不传则 reload 当前")


def _load_project_yaml_for_service(project_file: str) -> Dict[str, Any]:
    """从 project.yaml 读取工程元信息（不创建 Engine）。"""
    import yaml as _yaml

    if not os.path.isfile(project_file):
        raise HTTPException(status_code=404, detail=f"工程文件不存在: {project_file}")
    try:
        with open(project_file, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析 project.yaml 失败: {e}")
    return data


def _inspect_project_sources(project_file: Optional[str], source_overrides: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """调用 realtime_config_compiler 校验（进程内，无 subprocess）。

    todo.md §5.1：服务内部调用现有 inspect / validate / compile，
    不再 exec.CommandContext。

    project_file 可为 None：
      - source_overrides 非空且所有 file 都是绝对路径时不需要
      - source_overrides 非空但包含相对路径时用于解析 project_dir
      - source_overrides 为空时用于读取工程 YAML
    """
    from controller.realtime_config_compiler import SourceSpec, validate_sources

    project_dir = os.path.dirname(project_file) if project_file else None
    if source_overrides is None:
        if not project_file:
            raise HTTPException(status_code=400, detail="projectFile 不能为空")
        project = _load_project_yaml_for_service(project_file)
        sources_raw = project.get("sources") or []
    else:
        sources_raw = source_overrides
    specs = []
    for item in sources_raw:
        sid = item.get("id", "")
        sfile = item.get("file", "")
        if not sid or not sfile:
            raise HTTPException(status_code=400, detail=f"source 缺少 id 或 file: {item}")
        if os.path.isabs(sfile):
            abs_path = sfile
        else:
            # 相对路径必须借助 projectFile 或当前工程目录解析；禁止使用 cwd。
            if project_dir is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"source file 是相对路径且未指定 projectFile: {sfile}",
                )
            abs_path = os.path.join(project_dir, sfile)
        replicas = int(item.get("replicas", 1))
        specs.append(SourceSpec(source_id=sid, source_file=abs_path, replicas=replicas))
    try:
        result = validate_sources(specs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"校验失败: {e}")
    return {
        "ok": True,
        "valid": result.valid,
        "instances": [
            {
                "name": inst.name,
                "sourceId": inst.source_id,
                "sourceFile": inst.source_file,
                "replicaIndex": inst.replica_index,
                "originalName": inst.original_name,
            }
            for inst in result.instances
        ],
        "duplicates": [
            {
                "name": dup.name,
                "occurrences": [
                    {
                        "sourceId": occ.source_id,
                        "sourceFile": occ.source_file,
                        "replicaIndex": occ.replica_index,
                        "originalName": occ.original_name,
                    }
                    for occ in dup.occurrences
                ],
            }
            for dup in result.duplicates
        ],
    }


@app.post("/api/project/open")
def api_project_open(req: ProjectOpenRequest) -> Dict[str, Any]:
    """打开工程上下文（仅加载 YAML，不创建 Engine）。

    todo.md §4.4：Go 端完成新建/打开/添加 YAML/移除 YAML/修改副本数或 runtime 后
    通知服务重新加载；工程文件是事实来源。
    """
    b = get_binding()
    if b.runtime_state == RUNTIME_STATE_RUNNING:
        raise HTTPException(status_code=409, detail="Engine 运行中无法切换工程，请先停止运行")
    if not req.projectFile:
        raise HTTPException(status_code=400, detail="projectFile 不能为空")
    try:
        validation = _inspect_project_sources(req.projectFile)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"打开工程失败: {e}")
    project = _load_project_yaml_for_service(req.projectFile)
    set_project_context(
        b,
        project_file=req.projectFile,
        project_name=str(project.get("name") or os.path.basename(os.path.dirname(req.projectFile))),
        validation=validation,
    )
    return {
        "ok": True,
        "projectFile": b.project_file,
        "projectName": b.project_name,
        "validation": validation,
    }


@app.post("/api/project/reload")
def api_project_reload(req: ProjectReloadRequest) -> Dict[str, Any]:
    """重载工程上下文（Go 端修改 project.yaml 后调用）。"""
    b = get_binding()
    target = req.projectFile or b.project_file
    if not target:
        raise HTTPException(status_code=400, detail="没有当前工程，且未提供 projectFile")
    if b.runtime_state == RUNTIME_STATE_RUNNING:
        raise HTTPException(status_code=409, detail="Engine 运行中无法 reload，请先停止运行")
    try:
        validation = _inspect_project_sources(target)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"reload 失败: {e}")
    project = _load_project_yaml_for_service(target)
    set_project_context(
        b,
        project_file=target,
        project_name=str(project.get("name") or os.path.basename(os.path.dirname(target))),
        validation=validation,
    )
    return {"ok": True, "projectFile": target, "validation": validation}


@app.post("/api/project/close")
def api_project_close() -> Dict[str, Any]:
    """清空当前工程上下文。"""
    b = get_binding()
    if b.runtime_state == RUNTIME_STATE_RUNNING:
        raise HTTPException(status_code=409, detail="Engine 运行中无法关闭工程，请先停止运行")
    clear_project_context(b)
    return {"ok": True}


@app.get("/api/project/current")
def api_project_current() -> Dict[str, Any]:
    """返回当前工程上下文（无工程时 ok=false）。"""
    b = get_binding()
    if not b.project_file:
        return {"ok": False, "projectFile": None, "validation": None}
    return {
        "ok": True,
        "projectFile": b.project_file,
        "projectName": b.project_name,
        "validation": b.project_validation,
    }


class ProjectInspectRequest(BaseModel):
    sources: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="不传则使用工程文件中的 sources"
    )
    projectFile: Optional[str] = Field(default=None, description="工程文件路径")


@app.post("/api/project/inspect")
def api_project_inspect(req: ProjectInspectRequest) -> Dict[str, Any]:
    """进程内 inspect（todo.md §5.1）。

    仅修改：现在允许 sources 全部为绝对路径时不要求 projectFile
    或当前工程上下文。未传 sources 时仍要求 projectFile 或当前工程。
    """
    b = get_binding()
    target = req.projectFile or b.project_file

    # 未传 sources 时必须提供 projectFile（load project.yaml 读 sources）
    if req.sources is None or len(req.sources) == 0:
        if not target:
            raise HTTPException(status_code=400, detail="没有指定 projectFile 且未打开工程")
        return _inspect_project_sources(target, None)

    # 传了 sources：全部为绝对路径时不需要 projectFile
    if target is None:
        all_abs = all(
            os.path.isabs((item or {}).get("file", ""))
            for item in req.sources
        )
        if not all_abs:
            raise HTTPException(
                status_code=400,
                detail="sources 包含相对路径时必须指定 projectFile 或打开工程",
            )
        target = None  # 显式保持 None，让 _inspect_project_sources 不参与路径解析

    try:
        return _inspect_project_sources(target, req.sources)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"inspect 失败: {e}")


class ProjectCompileRequest(BaseModel):
    sources: List[Dict[str, Any]] = Field(..., description="[{id, file, replicas}]")
    output: str = Field(..., description="合并后的 YAML 绝对路径")


@app.post("/api/project/compile")
def api_project_compile(req: ProjectCompileRequest) -> Dict[str, Any]:
    """进程内 compile（todo.md §5.2）。"""
    from controller.realtime_config_compiler import SourceSpec, compile_project_to_file

    specs = []
    for item in req.sources:
        sid = item.get("id", "")
        sfile = item.get("file", "")
        if not sid or not sfile:
            raise HTTPException(status_code=400, detail=f"source 缺少 id 或 file: {item}")
        specs.append(SourceSpec(
            source_id=sid,
            source_file=sfile,
            replicas=int(item.get("replicas", 1)),
        ))
    try:
        out_path = compile_project_to_file(specs, req.output)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"compile 失败: {e}")
    return {"ok": True, "output": out_path}


# --------------------------------------------------------------------------- #
# todo.md §4.3 + §6：runtime 生命周期                                            #
# --------------------------------------------------------------------------- #

class RuntimeStartRequest(BaseModel):
    configPath: str = Field(..., description="合并后的 config YAML 绝对路径")
    runtimeName: str = Field(default="default")
    cycleTime: float = Field(default=0.5)
    opcUaHost: str = Field(default="0.0.0.0")
    opcUaPort: int = Field(default=18951)


def _start_runtime_internal(req: RuntimeStartRequest) -> Dict[str, Any]:
    """进程内启动 Engine + OPC UA（todo.md §6.1）。

    不创建新子进程；Engine 与 OPC UA 都在当前服务进程内。

    任何路径（包括 HTTPException）失败都必须清理本次已创建的资源
    （engine / engine_thread / stop_event / opcua_server / shared_data /
    force/quality manager / engine_holder），并把 runtime_state 恢复到可重新
    启动的状态（如 STOPPED 或 FAILED）。失败时不得残留半启动资源，也不得
    吞掉原始错误信息。
    """
    from controller.engine import UnifiedEngine
    from controller.parser import DSLParser
    from controller.clock import ClockMode
    from typing import Any as _Any

    b = get_binding()
    with b._state_lock:
        if b.runtime_state != RUNTIME_STATE_STOPPED and b.runtime_state != RUNTIME_STATE_FAILED:
            raise HTTPException(
                status_code=409,
                detail=f"当前运行状态 {b.runtime_state} 不允许启动；请先调用 /api/runtime/stop",
            )
        b.runtime_state = RUNTIME_STATE_STARTING

    # 检查 batch 互斥
    with _batch_lock:
        if _batch_running:
            with b._state_lock:
                b.runtime_state = RUNTIME_STATE_STOPPED
            raise HTTPException(status_code=409, detail="批量任务正在运行，禁止启动实时运行")

    if not os.path.isfile(req.configPath):
        with b._state_lock:
            b.runtime_state = RUNTIME_STATE_FAILED
        raise HTTPException(status_code=404, detail=f"config 文件不存在: {req.configPath}")

    # 跟踪本次启动创建的资源。任何路径失败都必须清理这些资源。
    created: Dict[str, _Any] = {}
    cleanup_called = False

    def _cleanup_partial() -> None:
        # 幂等：可能因为 stop_event 未设而 join 超时，但同样尝试 join。
        nonlocal cleanup_called
        if cleanup_called:
            return
        cleanup_called = True

        opcua_local = created.get("opcua_server")
        if opcua_local is not None:
            try:
                opcua_local.stop()
            except Exception:
                logger.exception("start-time cleanup: opcua stop error")
        thread_local = created.get("engine_thread")
        if thread_local is not None:
            try:
                thread_local.join(timeout=2.0)
            except Exception:
                logger.exception("start-time cleanup: thread join error")
        # 清空 binding 上被本次启动触达过的字段（保持 STOPPED 状态）
        with b._state_lock:
            # engine / opcua / thread / stop_event / engine_holder 不直接清，
            # 以便用户/前端能拿到错误上下文；但保证 runtime_state 可重新启动
            if b.runtime_state != RUNTIME_STATE_STOPPED:
                b.runtime_state = RUNTIME_STATE_STOPPED
        # 清空本次启动创建的资源对象引用，避免资源泄漏
        for k in (
            "engine",
            "engine_holder",
            "shared_data",
            "force_manager",
            "quality_manager",
            "opcua_server",
            "engine_thread",
            "engine_stop_event",
            "instance_name",
        ):
            if k in created:
                setattr(b, k, None if k != "instance_name" else None)

    try:
        parser = DSLParser()
        config = parser.parse_file(req.configPath)
        if req.cycleTime > 0:
            config.clock.cycle_time = req.cycleTime
        # 默认 REALTIME 模式
        config.clock.mode = ClockMode.REALTIME
        engine = UnifiedEngine.from_program_config(config)
        engine_holder: Dict[str, _Any] = {"engine": engine}
        # 共享数据 / 命令队列
        shared_data: Dict[str, float] = {}
        cmd_queue: queue.Queue = queue.Queue()

        # force / quality manager
        from datacenter.force_manager import ForceManager
        from datacenter.quality_manager import QualityManager
        force_manager = ForceManager()
        quality_manager = QualityManager()

        # engine thread
        stop_event = threading.Event()

        def _on_snapshot(snap: Dict[str, _Any]) -> None:
            b.push_snapshot(snap)

        def _engine_thread_main():
            try:
                # 与 standalone_main.run_engine_thread 一致：先解析后启动 engine
                engine.clock.start()
                while not stop_event.is_set():
                    while not cmd_queue.empty():
                        try:
                            cmd = cmd_queue.get_nowait()
                        except queue.Empty:
                            break
                        engine.override_variable(cmd["tag"], cmd["value"])
                    snap = engine.step()
                    for k, v in snap.items():
                        if k not in (
                            "cycle_count",
                            "need_sample",
                            "time_str",
                            "sim_time",
                            "exec_ratio",
                        ):
                            shared_data[k] = v
                    if b.alarm_manager is not None:
                        try:
                            b.alarm_manager.evaluate(snap)
                        except Exception:
                            pass
                    _on_snapshot(snap)
            except Exception:
                logger.exception("engine thread crashed")
            finally:
                engine.clock.stop()

        # OPC UA server
        from datacenter.opcua_server import OPCUAServerConfig, StandaloneOpcuaServer

        opcua_config = OPCUAServerConfig(
            server_url=f"opc.tcp://{req.opcUaHost}:{req.opcUaPort}",
            update_cycle=0.1,
            enable_write=True,
        )
        opcua_server = StandaloneOpcuaServer(
            config=opcua_config,
            shared_data=shared_data,
            cmd_queue=cmd_queue,
            force_manager=force_manager,
            quality_manager=quality_manager,
        )
        opcua_server.start()
        created["opcua_server"] = opcua_server

        if not opcua_server.wait_ready(timeout=5.0):
            raise HTTPException(
                status_code=503,
                detail=f"OPC UA 未在 5s 内就绪: {req.opcUaHost}:{req.opcUaPort}",
            )

        engine_thread = threading.Thread(
            target=_engine_thread_main,
            daemon=True,
            name=f"EngineThread-{req.runtimeName}",
        )
        engine_thread.start()
        created["engine_thread"] = engine_thread

        # 绑定到 EngineBinding（只在所有创建步骤成功后写入）
        b.engine = engine
        created["engine"] = engine
        b.engine_holder = engine_holder  # type: ignore[attr-defined]
        created["engine_holder"] = engine_holder
        b.shared_data = shared_data
        created["shared_data"] = shared_data
        b.force_manager = force_manager
        created["force_manager"] = force_manager
        b.quality_manager = quality_manager
        created["quality_manager"] = quality_manager
        b.opcua_server = opcua_server  # type: ignore[attr-defined]
        b.engine_thread = engine_thread  # type: ignore[attr-defined]
        b.engine_stop_event = stop_event  # type: ignore[attr-defined]
        created["engine_stop_event"] = stop_event
        # todo.md §10.1：更新 instance_name
        b.instance_name = req.runtimeName
        created["instance_name"] = req.runtimeName

        with b._state_lock:
            b.runtime_state = RUNTIME_STATE_RUNNING
        return {
            "ok": True,
            "runtimeState": b.runtime_state,
            "cycleTime": req.cycleTime,
            "opcUaHost": req.opcUaHost,
            "opcUaPort": req.opcUaPort,
            "runtimeName": req.runtimeName,
        }
    except HTTPException:
        _cleanup_partial()
        raise
    except Exception as e:
        logger.exception("start runtime failed")
        _cleanup_partial()
        # 把原始 e 包进 detail 保留
        raise HTTPException(status_code=500, detail=f"启动运行失败: {e}")


@app.post("/api/runtime/start")
def api_runtime_start(req: RuntimeStartRequest) -> Dict[str, Any]:
    return _start_runtime_internal(req)


@app.get("/api/runtime/status")
def api_runtime_status() -> Dict[str, Any]:
    b = get_binding()
    with b._state_lock:
        return {
            "ok": True,
            "runtimeState": b.runtime_state,
            "serviceState": b.service_state,
        }


@app.post("/api/runtime/stop")
def api_runtime_stop() -> Dict[str, Any]:
    """进程内停止 Engine + OPC UA（todo.md §10.3-§10.4）。不停止 DataFactoryService。

    幂等：
      - STOPPED 且无残留资源 → 直接 noop 返回
      - STOPPED 但有残留资源（之前 timeout 没清掉）→ 重新尝试清理
      - FAILED 同上 → 必须重试，因为失败可能留下半启动资源
      - RUNNING/STARTING/STOPPING → 正常停止流程
    """
    b = get_binding()

    def _has_running_resource() -> bool:
        return any(
            getattr(b, k, None) is not None
            for k in (
                "engine",
                "engine_thread",
                "engine_stop_event",
                "opcua_server",
            )
        )

    with b._state_lock:
        # 仅当已 STOPPED 且无任何残留资源时才允许完全 noop。
        # FAILED/STOPPED 但有残留资源 → 必须重试清理。
        if b.runtime_state == RUNTIME_STATE_STOPPED and not _has_running_resource():
            return {"ok": True, "runtimeState": b.runtime_state, "noop": True}
        # FAILED 状态下也允许重试：尝试再次清理并把状态切到 STOPPING。
        if b.runtime_state in (RUNTIME_STATE_STOPPED, RUNTIME_STATE_FAILED):
            logger.warning(
                "runtime state=%s but still has running resource; retrying stop",
                b.runtime_state,
            )
        b.runtime_state = RUNTIME_STATE_STOPPING

    # OPC UA 先停（依赖 force/quality state）；Engine 线程设置 stop_event 让循环退出
    stop_thread_timeout = False
    try:
        opcua = getattr(b, "opcua_server", None)
        if opcua is not None:
            try:
                opcua.stop()
            except Exception:
                logger.exception("opcua stop error")

        stop_event = getattr(b, "engine_stop_event", None)
        if stop_event is not None:
            stop_event.set()

        thread = getattr(b, "engine_thread", None)
        if thread is not None:
            thread.join(timeout=5.0)  # todo.md §10.3：增加超时时间
            # todo.md §10.3：检查线程是否真正退出
            if thread.is_alive():
                stop_thread_timeout = True
                # 保留 retry 能力：资源未清，但状态进入 FAILED
                with b._state_lock:
                    b.runtime_state = RUNTIME_STATE_FAILED
                raise HTTPException(
                    status_code=500,
                    detail="Engine 线程在 5s 内未退出，停止失败",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("runtime stop error")
        with b._state_lock:
            b.runtime_state = RUNTIME_STATE_FAILED
        raise HTTPException(status_code=500, detail=f"停止运行失败: {e}")

    # todo.md §10.4：stop 成功后清空全部运行期状态
    b.engine = None
    b.shared_data = {}
    b.force_manager = None
    b.quality_manager = None
    b.opcua_server = None  # type: ignore[attr-defined]
    b.engine_thread = None  # type: ignore[attr-defined]
    b.engine_stop_event = None  # type: ignore[attr-defined]
    b.engine_holder = None  # type: ignore[attr-defined]
    # 清空 snapshot
    with b._latest_snapshot_lock:
        b._latest_snapshot = None
    with b._buffer_lock:
        b.snapshot_buffer.clear()
    # 清空归档和报警运行状态
    b.archiver = None
    b.alarm_manager = None

    with b._state_lock:
        b.runtime_state = RUNTIME_STATE_STOPPED

    return {"ok": True, "runtimeState": b.runtime_state, "stopThreadTimeout": stop_thread_timeout}


# ---------------------------------------------------------------------------
# batch 异步仿真 + SQLite 存储（批量仿真结果本地化改造）
# ---------------------------------------------------------------------------

from datacenter.batch_manager import (
    BatchManager,
    BatchConflictError,
    BatchNotFoundError,
    BatchValidationError,
)


def _batch_http_status(exc: Exception) -> int:
    if isinstance(exc, BatchConflictError):
        return 409
    if isinstance(exc, BatchNotFoundError):
        return 404
    if isinstance(exc, BatchValidationError):
        return 400
    return 500


def _init_batch_manager() -> None:
    """注入实时运行状态检查函数 + 启动扫描。"""
    mgr = BatchManager.instance()

    def _is_realtime_running() -> bool:
        b = get_binding()
        with b._state_lock:
            return b.runtime_state in (RUNTIME_STATE_RUNNING, RUNTIME_STATE_STARTING, RUNTIME_STATE_STOPPING)

    mgr.set_runtime_check(_is_realtime_running)
    mgr.startup_scan()


class BatchRunRequest(BaseModel):
    configPath: str = Field(..., description="config YAML 绝对路径")
    cycles: int = Field(..., description="运行周期数")
    cycleTime: Optional[float] = Field(default=None, description="覆盖周期时间")


@app.post("/api/batch/run")
def api_batch_run(req: BatchRunRequest) -> Dict[str, Any]:
    """异步启动 batch 仿真，立即返回 batchId。不再返回 rows。"""
    try:
        mgr = BatchManager.instance()
        batch_id = mgr.start_batch(req.configPath, req.cycles, req.cycleTime)
        return {"ok": True, "batchId": batch_id, "status": "running"}
    except (BatchConflictError, BatchValidationError, BatchNotFoundError) as e:
        raise HTTPException(status_code=_batch_http_status(e), detail=str(e))
    except Exception as e:
        logger.exception("batch start failed")
        raise HTTPException(status_code=500, detail=f"启动批量仿真失败: {e}")


@app.get("/api/batch/runs/{batchId}")
def api_batch_status(batchId: str) -> Dict[str, Any]:
    """查询 batch 任务状态。"""
    try:
        return BatchManager.instance().get_status(batchId)
    except BatchNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("batch status failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/batch/runs/{batchId}/cancel")
def api_batch_cancel(batchId: str) -> Dict[str, Any]:
    """取消正在运行的 batch 任务。"""
    try:
        return BatchManager.instance().cancel(batchId)
    except (BatchConflictError, BatchNotFoundError) as e:
        raise HTTPException(status_code=_batch_http_status(e), detail=str(e))
    except Exception as e:
        logger.exception("batch cancel failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batch/runs/{batchId}/rows")
def api_batch_rows(batchId: str, offset: int = 0, limit: int = 200) -> Dict[str, Any]:
    """分页读取 batch 预览行。默认 limit=200，最大 1000。"""
    try:
        return BatchManager.instance().get_rows(batchId, offset, limit)
    except BatchNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("batch rows failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/batch/runs/{batchId}")
def api_batch_delete(batchId: str) -> Dict[str, Any]:
    """删除 batch 结果。不得删除正在运行的任务。"""
    try:
        return BatchManager.instance().delete(batchId)
    except (BatchConflictError, BatchNotFoundError) as e:
        raise HTTPException(status_code=_batch_http_status(e), detail=str(e))
    except Exception as e:
        logger.exception("batch delete failed")
        raise HTTPException(status_code=500, detail=str(e))


class ExportConvertRequest(BaseModel):
    batchId: str = Field(..., description="batch 任务 ID")
    columns: List[str] = Field(default_factory=list, description="列名列表，空则用全部")
    exportPath: str = Field(..., description="输出文件路径")
    format: str = Field(default="csv", description="csv / xlsx")
    sheetName: Optional[str] = Field(default="控制器")


@app.post("/api/export/convert")
def api_export_convert(req: ExportConvertRequest) -> Dict[str, Any]:
    """从 SQLite 流式导出 batch 结果。不再接收 rows。"""
    if req.format not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail=f"不支持的格式: {req.format}")
    try:
        return BatchManager.instance().export(
            batch_id=req.batchId,
            columns=req.columns,
            export_path=req.exportPath,
            fmt=req.format,
            sheet_name=req.sheetName or "",
        )
    except (BatchConflictError, BatchValidationError, BatchNotFoundError) as e:
        raise HTTPException(status_code=_batch_http_status(e), detail=str(e))
    except Exception as e:
        logger.exception("export convert failed")
        raise HTTPException(status_code=500, detail=f"export 失败: {e}")


# ---------------------------------------------------------------------------
# todo.md §10.5：Engine 未运行接口统一返回 409
# ---------------------------------------------------------------------------

def _require_engine_running(b: "EngineBinding") -> None:
    """检查 Engine 是否运行中，未运行则抛 409（todo.md §10.5）。"""
    if b.engine is None:
        raise HTTPException(status_code=409, detail="当前工程未运行")


@app.get("/api/instances/{name}/meta")
def api_meta(name: str) -> Dict[str, Any]:
    """所有 program 项的 stored_attributes + default_params + param_descriptions。"""
    b = get_binding()
    _require_engine_running(b)  # todo.md §10.5
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
    _require_engine_running(b)  # todo.md §10.5
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
    _require_engine_running(b)  # todo.md §10.5
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
    _require_engine_running(b)  # todo.md §10.5
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
    _require_engine_running(b)  # todo.md §10.5
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
# 质量码覆盖                                                                   #
# --------------------------------------------------------------------------- #

class QualitySetRequest(BaseModel):
    tag: str
    quality: str


def _refresh_quality_valid_tags(b: "EngineBinding") -> None:
    """质量码合法集合与 force 一致：来自 shared_data 数值键。"""
    if b.quality_manager is None:
        return
    tags = {k for k, v in b.shared_data.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}
    b.quality_manager.set_valid_tags(tags)


@app.post("/api/quality")
def api_quality_set(req: QualitySetRequest) -> Dict[str, Any]:
    """写入 / 清除 OPC UA 质量码覆盖。quality == 'Good' 表示清除。"""
    from datacenter.quality_manager import QualityError
    b = get_binding()
    if b.quality_manager is None:
        raise HTTPException(status_code=503, detail="质量码层未启用")
    _refresh_quality_valid_tags(b)
    try:
        applied = b.quality_manager.set_quality(req.tag, req.quality)
    except QualityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "tag": req.tag, "quality": applied}


@app.delete("/api/quality/{tag}")
def api_quality_clear(tag: str) -> Dict[str, Any]:
    b = get_binding()
    if b.quality_manager is None:
        raise HTTPException(status_code=503, detail="质量码层未启用")
    b.quality_manager.clear_quality(tag)
    return {"ok": True, "tag": tag}


@app.get("/api/quality")
def api_quality_list() -> Dict[str, Any]:
    b = get_binding()
    _refresh_quality_valid_tags(b)
    if b.quality_manager is None:
        return {"ok": True, "qualities": {}, "tags": []}
    tags = sorted(b.quality_manager.snapshot_valid_tags())
    return {"ok": True, "qualities": b.quality_manager.snapshot(), "tags": tags}


# --------------------------------------------------------------------------- #
# 报警                                                                         #
# --------------------------------------------------------------------------- #

class AlarmRulePayload(BaseModel):
    id: str
    name: str
    tag: str
    direction: str
    limit: float
    severity: str
    delay_seconds: float = 0.0
    deadband: float = 0.0
    enabled: bool = True
    message: str = ""


class AlarmConfigRequest(BaseModel):
    rules: List[AlarmRulePayload]


@app.post("/api/alarms/config")
def api_alarm_config(req: AlarmConfigRequest) -> Dict[str, Any]:
    from datacenter.alarm_manager import AlarmManager, AlarmRuleSpec
    b = get_binding()
    specs = [AlarmRuleSpec(**r.dict()) for r in req.rules]
    b.alarm_manager = AlarmManager(specs)
    return {"ok": True, "count": len(specs)}


@app.get("/api/alarms")
def api_alarms() -> Dict[str, Any]:
    b = get_binding()
    if b.alarm_manager is None:
        return {"ok": True, "alarms": []}
    return {"ok": True, "alarms": b.alarm_manager.statuses()}


@app.post("/api/alarms/{alarm_id}/ack")
def api_alarm_ack(alarm_id: str) -> Dict[str, Any]:
    b = get_binding()
    if b.alarm_manager is None:
        raise HTTPException(status_code=404, detail="报警未启用")
    ok = b.alarm_manager.acknowledge(alarm_id)
    if not ok:
        raise HTTPException(status_code=400, detail="报警不可确认")
    return {"ok": True}


@app.post("/api/alarms/ack-all")
def api_alarm_ack_all() -> Dict[str, Any]:
    b = get_binding()
    if b.alarm_manager is None:
        return {"ok": True, "acked": 0}
    return {"ok": True, "acked": b.alarm_manager.acknowledge_all()}


@app.get("/api/alarm-events")
def api_alarm_events(limit: Optional[int] = None) -> Dict[str, Any]:
    b = get_binding()
    if b.alarm_manager is None:
        return {"ok": True, "events": []}
    return {"ok": True, "events": b.alarm_manager.events(limit)}


# --------------------------------------------------------------------------- #
# 运行归档                                                                     #
# --------------------------------------------------------------------------- #

def _history_base() -> str:
    cache = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    return str(Path(cache) / "DataFactory" / "run_history")


class ArchiveStartRequest(BaseModel):
    sessionId: str
    tags: List[str]
    metadata: Dict[str, Any] = {}


@app.post("/api/archive/start")
def api_archive_start(req: ArchiveStartRequest) -> Dict[str, Any]:
    from datacenter.run_archiver import RunArchiver
    b = get_binding()
    if b.archiver is not None:
        try:
            b.archiver.close()
        except Exception:
            pass
    archiver = RunArchiver(_history_base(), req.sessionId, req.metadata, req.tags)
    archiver.start()
    b.archiver = archiver
    return {"ok": True, "sessionId": req.sessionId, "tags": req.tags}


@app.post("/api/archive/stop")
def api_archive_stop() -> Dict[str, Any]:
    b = get_binding()
    if b.archiver is not None:
        try:
            b.archiver.close()
        except Exception:
            pass
        b.archiver = None
    return {"ok": True}


@app.get("/api/history")
def api_history_list() -> Dict[str, Any]:
    from datacenter.run_archiver import RunHistory
    h = RunHistory(_history_base())
    return {"ok": True, "runs": h.list_runs(), "diskUsageBytes": h.disk_usage_bytes()}


@app.get("/api/history/{session_id}/values")
def api_history_values(session_id: str) -> Dict[str, Any]:
    from datacenter.run_archiver import RunHistory
    h = RunHistory(_history_base())
    return {"ok": True, "values": h.read_values(session_id)}


@app.post("/api/history/{session_id}/export")
def api_history_export(session_id: str, req: ExportRequest) -> Dict[str, Any]:
    from datacenter.run_archiver import RunHistory
    h = RunHistory(_history_base())
    n = h.export_csv(session_id, req.path)
    return {"ok": True, "rows": n, "path": req.path}


@app.delete("/api/history/{session_id}")
def api_history_delete(session_id: str) -> Dict[str, Any]:
    from datacenter.run_archiver import RunHistory
    h = RunHistory(_history_base())
    ok = h.delete_run(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="历史运行不存在")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# WebSocket                                                                   #
# --------------------------------------------------------------------------- #

@app.websocket("/ws/snapshot")
async def ws_snapshot(ws: WebSocket) -> None:
    """
    每周期推一次 snapshot；支持客户端订阅协议。

    订阅协议（新客户端）：
        {"type": "subscribe", "tags": ["pid.PV", "pid.SV"], "includeMeta": true}
    旧客户端不发 subscribe 时保持全量行为。
    非法 tag 返回结构化错误：{"type": "error", "code": "INVALID_TAG", ...}。

    心跳：1s 内未收到真实 snapshot，发送 ``{"_heartbeat": true, "ts": ...}``。
    """
    await ws.accept()
    if not _auth_disabled() and _api_token is not None:
        token = ws.query_params.get("token")
        if token != _api_token:
            await ws.close(code=4401)
            return
    b = get_binding()
    my_queue = b.broadcaster.register()
    logger.info("WS client connected, total clients=%d",
                b.broadcaster.client_count())

    async def sender() -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                snapshot = await loop.run_in_executor(None, my_queue.get, True, 1.0)
            except queue.Empty:
                await ws.send_json({"_heartbeat": True, "ts": time.time()})
                continue
            await ws.send_json(snapshot)

    async def receiver() -> None:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "subscribe":
                tags = msg.get("tags")
                if tags is None:
                    b.broadcaster.subscribe(my_queue, None)
                    await ws.send_json({"type": "subscribed", "tags": None})
                    continue
                if not isinstance(tags, list):
                    await ws.send_json({"type": "error", "code": "INVALID_SUBSCRIBE", "message": "tags 必须是数组"})
                    continue
                if len(tags) > _WsBroadcaster.MAX_SUBSCRIPTIONS:
                    await ws.send_json({"type": "error", "code": "TOO_MANY_SUBSCRIPTIONS",
                                        "message": f"订阅数超过上限 {_WsBroadcaster.MAX_SUBSCRIPTIONS}"})
                    continue
                tagset = {str(t) for t in tags}
                b.broadcaster.subscribe(my_queue, tagset)
                await ws.send_json({"type": "subscribed", "tags": sorted(tagset)})

    try:
        await asyncio.gather(sender(), receiver())
    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    except Exception as e:
        logger.error("WS error: %s", e, exc_info=True)
    finally:
        b.broadcaster.unregister(my_queue)


# --------------------------------------------------------------------------- #
# uvicorn 启动入口                                                            #
# --------------------------------------------------------------------------- #

def run_api_server(binding: EngineBinding, host: str, port: int, api_token: Optional[str] = None) -> threading.Thread:
    """
    在新线程里启动 uvicorn + FastAPI。

    Returns: daemon 线程句柄，调用方可 join。
    """
    set_binding(binding)
    set_api_token(api_token)

    import uvicorn

    # PyInstaller console=False → sys.stderr=None → uvicorn DefaultFormatter
    # 初始化时会调 sys.stderr.isatty() 抛 AttributeError，最终导致
    # dictConfig 报 "Unable to configure formatter 'default'"。禁用 uvicorn
    # 自带 logging 配置，走 Python 标准 logging（已在 main 中初始化）。
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
        access_log=False,
        log_config=None,
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