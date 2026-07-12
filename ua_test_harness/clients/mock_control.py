"""clients/mock_control.py:Mock 启停 / 状态查询。

复用 ua_test_harness.env.mock_manager(已在 provision 等命令里使用)。
"""
from __future__ import annotations

from ua_test_harness.context import RunContext


def start_mock(key: str) -> int:
    from ua_test_harness.env.mock_manager import MockManager, all_specs

    mgr = MockManager()
    spec = {s.key: s for s in all_specs()}[key]
    rt = mgr.start(spec)
    return rt.pid


def stop_mock(key: str) -> None:
    from ua_test_harness.env.mock_manager import MockManager

    MockManager().stop(key)


def status(key: str) -> str:
    from ua_test_harness.env.mock_manager import MockManager

    return MockManager().status(key)


def wait_ready(key: str, timeout: float = 60.0, ctx: RunContext | None = None) -> None:
    from ua_test_harness.polling import wait_until

    wait_until(f"mock_{key}_ready", lambda: status(key) in ("ready", "running"), timeout=timeout, interval=1.0)


def get_endpoint(key: str, ctx: RunContext | None = None) -> str:
    """从 RunConfig 取 mock endpoint;无则按 key + 本机 IP 兜底。"""
    if ctx is not None:
        from .tpt_client import endpoint_for
        return endpoint_for(key, ctx)
    port = {"functional": 18960, "reconnect": 18961, "performance": 18962, "abnormal": 18963}.get(key, 18960)
    return f"opc.tcp://127.0.0.1:{port}/ua_mocker/"