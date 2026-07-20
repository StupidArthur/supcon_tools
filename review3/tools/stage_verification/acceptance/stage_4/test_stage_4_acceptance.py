"""Stage 4 reviewer acceptance: real Uvicorn HTTP/WebSocket contracts."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

# Project root on sys.path for datacenter + controller imports.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import components.programs  # noqa: F401 — register algorithms

from controller.clock import ClockMode
from controller.engine import UnifiedEngine
from controller.parser import DSLParser
from datacenter import engine_api
from tools.stage_verification.common.ports import (
    reserve_tcp_port,
    wait_http_ready,
    wait_port_released,
)
from tools.stage_verification.common.process import ManagedProcess
from tools.stage_verification.common.workspace import copy_template_fixture


def _build_engine(yaml_path: str, cycle_time: float = 0.5) -> UnifiedEngine:
    config = DSLParser().parse_file(yaml_path)
    config.clock.cycle_time = cycle_time
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR
    return engine


def _make_binding(
    instance_name: str = "stage4_acceptance_runtime",
    *,
    yaml_path: str,
    cycle_time: float = 0.5,
) -> engine_api.EngineBinding:
    engine = _build_engine(yaml_path, cycle_time=cycle_time)
    shared: Dict[str, float] = {}
    binding = engine_api.EngineBinding(
        instance_name=instance_name,
        engine=engine,
        shared_data=shared,
    )

    def drive(n: int = 1) -> None:
        engine.clock.start()
        for _ in range(n):
            snap = engine.step()
            for key, value in snap.items():
                if key not in (
                    "cycle_count",
                    "need_sample",
                    "time_str",
                    "sim_time",
                    "exec_ratio",
                ):
                    shared[key] = value
            binding.push_snapshot(snap)
        engine.clock.stop()

    drive(2)
    binding._drive_test = drive  # type: ignore[attr-defined]
    return binding


def _http_json(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_status_code(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5.0) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


class _UvicornHarness:
  """Start/stop real uvicorn on a reserved port."""

  def __init__(self, binding: engine_api.EngineBinding, host: str = "127.0.0.1") -> None:
      self.binding = binding
      self.host = host
      self.port = reserve_tcp_port(host)
      self._server: Any = None
      self._thread: threading.Thread | None = None

  def start(self) -> None:
      import uvicorn

      engine_api.set_binding(self.binding)
      config = uvicorn.Config(
          engine_api.app,
          host=self.host,
          port=self.port,
          log_level="error",
          access_log=False,
      )
      self._server = uvicorn.Server(config)

      def _run() -> None:
          self._server.run()

      self._thread = threading.Thread(target=_run, daemon=True, name="stage4-uvicorn")
      self._thread.start()
      wait_http_ready(f"http://{self.host}:{self.port}/api/status")

  def stop(self) -> None:
      if self._server is not None:
          self._server.should_exit = True
      if self._thread is not None:
          self._thread.join(timeout=10.0)
      engine_api.set_binding(None)  # type: ignore[arg-type]
      wait_port_released(self.port, host=self.host)

  @property
  def base_url(self) -> str:
      return f"http://{self.host}:{self.port}"


@pytest.fixture
def yaml_fixture(tmp_path: Path, verifier_root: Path) -> Path:
    return copy_template_fixture(tmp_path, verifier_root=verifier_root)


@pytest.fixture
def uvicorn_server(yaml_fixture: Path) -> Iterator[_UvicornHarness]:
    binding = _make_binding(yaml_path=str(yaml_fixture))
    harness = _UvicornHarness(binding)
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


def test_stage_4_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_4/test_stage_4_acceptance.py",
        "config-tool/frontend/acceptance/stage_4/runtime_api.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_4/runtime_store.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_4/runtime_diagram.acceptance.test.tsx",
    ]
    missing = [path for path in required if not (project_root / path).is_file()]
    assert not missing, f"missing reviewer acceptance files: {missing}"


def test_network_status_instance_name_drives_runtime_name(uvicorn_server: _UvicornHarness) -> None:
    status = _http_json(f"{uvicorn_server.base_url}/api/status")
    runtime_name = status["instance_name"]
    assert runtime_name == "stage4_acceptance_runtime"
    assert runtime_name not in ("pid2", "tank_2")

    meta = _http_json(
        f"{uvicorn_server.base_url}/api/instances/{runtime_name}/meta"
    )
    assert meta["instance_name"] == runtime_name

    snapshot = _http_json(
        f"{uvicorn_server.base_url}/api/instances/{runtime_name}/snapshot"
    )
    assert isinstance(snapshot, dict)
    assert snapshot["cycle_count"] == status["cycle_count"]
    assert snapshot["sim_time"] == status["sim_time"]


def test_network_wrong_runtime_name_returns_404(uvicorn_server: _UvicornHarness) -> None:
    code = _http_status_code(
        f"{uvicorn_server.base_url}/api/instances/not_a_real_runtime/snapshot"
    )
    assert code == 404


def test_network_snapshot_has_no_data_wrapper(uvicorn_server: _UvicornHarness) -> None:
    status = _http_json(f"{uvicorn_server.base_url}/api/status")
    runtime_name = status["instance_name"]
    snapshot = _http_json(
        f"{uvicorn_server.base_url}/api/instances/{runtime_name}/snapshot"
    )
    assert "data" not in snapshot or "cycle_count" in snapshot
    required_tags = [
        "valve_1.current_opening",
        "tank_2.level",
        "pid2.SV",
        "pid2.MV",
    ]
    for tag in required_tags:
        assert tag in snapshot, f"missing required tag {tag}"


def test_network_cycle_count_and_sim_time_advance(uvicorn_server: _UvicornHarness) -> None:
    binding = uvicorn_server.binding
    status = _http_json(f"{uvicorn_server.base_url}/api/status")
    runtime_name = status["instance_name"]
    snap_before = _http_json(
        f"{uvicorn_server.base_url}/api/instances/{runtime_name}/snapshot"
    )
    cc0 = snap_before["cycle_count"]
    st0 = snap_before["sim_time"]

    binding._drive_test(5)  # type: ignore[attr-defined]

    snap_after = _http_json(
        f"{uvicorn_server.base_url}/api/instances/{runtime_name}/snapshot"
    )
    status_after = _http_json(f"{uvicorn_server.base_url}/api/status")
    assert snap_after["cycle_count"] > cc0
    assert snap_after["sim_time"] > st0
    assert status_after["cycle_count"] == snap_after["cycle_count"]
    assert status_after["sim_time"] == snap_after["sim_time"]


@pytest.mark.asyncio
async def test_network_websocket_delivers_full_snapshot(uvicorn_server: _UvicornHarness) -> None:
    import websockets

    binding = uvicorn_server.binding
    ws_url = f"ws://{uvicorn_server.host}:{uvicorn_server.port}/ws/snapshot"
    async with websockets.connect(ws_url, open_timeout=5) as ws:
        binding._drive_test(1)  # type: ignore[attr-defined]
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        payload = json.loads(raw)
        while payload.get("_heartbeat") is True:
            binding._drive_test(1)  # type: ignore[attr-defined]
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            payload = json.loads(raw)
        assert payload.get("_heartbeat") is not True
        assert "cycle_count" in payload
        assert "valve_1.current_opening" in payload
        assert "data" not in payload


@pytest.mark.asyncio
async def test_network_websocket_heartbeat_does_not_replace_snapshot(
    uvicorn_server: _UvicornHarness,
) -> None:
    import websockets

    binding = uvicorn_server.binding
    ws_url = f"ws://{uvicorn_server.host}:{uvicorn_server.port}/ws/snapshot"
    async with websockets.connect(ws_url, open_timeout=5) as ws:
        binding._drive_test(1)  # type: ignore[attr-defined]
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        while first.get("_heartbeat") is True:
            binding._drive_test(1)  # type: ignore[attr-defined]
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        assert first.get("_heartbeat") is not True
        cc_before = first["cycle_count"]

        deadline = time.monotonic() + 3.0
        saw_heartbeat = False
        while time.monotonic() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
            except asyncio.TimeoutError:
                break
            if msg.get("_heartbeat") is True:
                saw_heartbeat = True
                assert "cycle_count" not in msg
                break
            assert msg.get("cycle_count") == cc_before

        assert saw_heartbeat, "expected heartbeat when engine is idle"


def test_slow_consumer_does_not_block_engine_publish(uvicorn_server: _UvicornHarness) -> None:
    binding = uvicorn_server.binding
    broadcaster = binding.broadcaster
    client_queue = broadcaster.register()
    try:
        start = time.perf_counter()
        for i in range(200):
            broadcaster.publish({"cycle_count": i, "valve_1.current_opening": float(i)})
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, "publish loop blocked — slow consumer must not stall engine"
        latest = client_queue.get(timeout=1.0)
        assert latest["cycle_count"] == 199
    finally:
        broadcaster.unregister(client_queue)


def test_multiple_ws_clients_share_single_engine_binding(uvicorn_server: _UvicornHarness) -> None:
    binding = uvicorn_server.binding
    before = binding.broadcaster.client_count()
    queues = [binding.broadcaster.register() for _ in range(3)]
    try:
        assert binding.broadcaster.client_count() == before + 3
        binding.push_snapshot({"cycle_count": 99, "sim_time": 49.5})
        for q in queues:
            msg = q.get(timeout=1.0)
            assert msg["cycle_count"] == 99
    finally:
        for q in queues:
            binding.broadcaster.unregister(q)


def test_empty_snapshot_does_not_refresh_received_at_contract(
    yaml_fixture: Path,
) -> None:
    engine = _build_engine(str(yaml_fixture))
    binding = engine_api.EngineBinding(
        instance_name="not_started_yet",
        engine=engine,
        shared_data={},
    )
    engine_api.set_binding(binding)
    try:
        snap = engine_api.api_snapshot("not_started_yet")
        assert snap == {}
        assert "cycle_count" not in snap
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]


def test_standalone_main_real_process_when_available(
    yaml_fixture: Path,
    project_root: Path,
) -> None:
    """Optional real DataFactory process acceptance (skipped when entry missing)."""
    entry = project_root / "standalone_main.py"
    if not entry.is_file():
        pytest.skip("standalone_main.py not present")

    api_port = reserve_tcp_port()
    opc_port = reserve_tcp_port()
    runtime_name = f"stage4_acceptance_{api_port}"

    argv = [
        sys.executable,
        str(entry),
        "-c",
        str(yaml_fixture),
        "--mode",
        "REALTIME",
        "--cycle-time",
        "0.05",
        "--name",
        runtime_name,
        "--api",
        "--api-host",
        "127.0.0.1",
        "--api-port",
        str(api_port),
        "--port",
        str(opc_port),
    ]

    proc = ManagedProcess.start(argv, cwd=project_root)
    try:
        wait_http_ready(f"http://127.0.0.1:{api_port}/api/status", timeout_seconds=60.0)
        status = _http_json(f"http://127.0.0.1:{api_port}/api/status")
        assert status["instance_name"] == runtime_name

        snapshots: List[Dict[str, Any]] = []
        deadline = time.monotonic() + 15.0
        while len(snapshots) < 3 and time.monotonic() < deadline:
            snap = _http_json(
                f"http://127.0.0.1:{api_port}/api/instances/{runtime_name}/snapshot"
            )
            if snap.get("cycle_count") is not None:
                snapshots.append(snap)
            time.sleep(0.05)

        assert len(snapshots) >= 3, "expected at least three real snapshots from running engine"
        counts = [s["cycle_count"] for s in snapshots]
        assert counts == sorted(counts) and counts[-1] > counts[0]
    finally:
        proc.stop()
        proc.assert_stopped()
        wait_port_released(api_port)
        wait_port_released(opc_port)
