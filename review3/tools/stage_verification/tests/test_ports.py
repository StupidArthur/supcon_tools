"""Tests for random-port and HTTP readiness helpers."""

from __future__ import annotations

import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tools.stage_verification.common.ports import (
    PortTimeoutError,
    reserve_tcp_port,
    wait_http_ready,
    wait_port_released,
)


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class PortsTests(unittest.TestCase):
    def test_reserve_tcp_port_returns_bindable_ephemeral_port(self) -> None:
        port = reserve_tcp_port()
        self.assertTrue(1024 <= port <= 65535)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))

    def test_wait_http_ready_and_port_release(self) -> None:
        port = reserve_tcp_port()
        server = HTTPServer(("127.0.0.1", port), _OkHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status = wait_http_ready(f"http://127.0.0.1:{port}/", timeout_seconds=5.0)
            self.assertEqual(200, status)
        finally:
            server.shutdown()
            server.server_close()
        wait_port_released(port, timeout_seconds=5.0)

    def test_wait_http_ready_times_out(self) -> None:
        port = reserve_tcp_port()
        with self.assertRaises(PortTimeoutError):
            wait_http_ready(f"http://127.0.0.1:{port}/missing", timeout_seconds=0.3)


if __name__ == "__main__":
    unittest.main()
