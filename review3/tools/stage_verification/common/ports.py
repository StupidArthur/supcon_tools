"""TCP port reservation and readiness helpers for acceptance tests.

Public API:
- reserve_tcp_port()
- wait_http_ready()
- wait_port_released()
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from contextlib import closing
from typing import Callable

# Defaults live at module top so readiness timing can be tuned during debugging.
DEFAULT_HTTP_READY_TIMEOUT_SECONDS = 30.0
DEFAULT_PORT_RELEASE_TIMEOUT_SECONDS = 10.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.05


class PortTimeoutError(TimeoutError):
    """Raised when a port/HTTP readiness wait exceeds its deadline."""


def reserve_tcp_port(host: str = "127.0.0.1") -> int:
    """Bind an ephemeral TCP port and return it after releasing the socket.

    Callers must start their server promptly; this only avoids hard-coded ports.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def wait_port_released(
    port: int,
    *,
    host: str = "127.0.0.1",
    timeout_seconds: float = DEFAULT_PORT_RELEASE_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Block until *port* refuses connections or raise PortTimeoutError."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _port_in_use(port, host=host):
            return
        time.sleep(poll_interval_seconds)
    raise PortTimeoutError(
        f"Port {host}:{port} still in use after {timeout_seconds:.1f}s"
    )


def wait_http_ready(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_HTTP_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    accept_status: Callable[[int], bool] | None = None,
) -> int:
    """Poll *url* until an acceptable HTTP status is returned.

    By default any HTTP response (including 4xx/5xx) counts as "server up".
    Connection failures keep polling until timeout.
    """
    if accept_status is None:
        accept_status = lambda status: True  # noqa: E731 — intentional default
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                status = int(getattr(response, "status", 200))
                if accept_status(status):
                    return status
        except urllib.error.HTTPError as exc:
            # HTTPError is also a response; server is listening.
            status = int(exc.code)
            if accept_status(status):
                return status
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(poll_interval_seconds)
    raise PortTimeoutError(
        f"HTTP endpoint not ready within {timeout_seconds:.1f}s: {url}; last={last_error}"
    )
