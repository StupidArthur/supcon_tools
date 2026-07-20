"""Windows/POSIX process-tree cleanup and port-rebind tests."""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tools.stage_verification.verifier import StageVerifier


CHILD_SCRIPT = r"""
import socket
import subprocess
import sys
import time

port = int(sys.argv[1])
hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
hold.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
hold.bind(("127.0.0.1", port))
hold.listen(1)
# Spawn a grandchild that also blocks so the tree has depth.
grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(30)"],
)
try:
    time.sleep(30)
finally:
    grandchild.kill()
"""


class ProcessCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "locked.txt").write_text("locked\n", encoding="utf-8")
        (self.root / "acceptance_test.py").write_text(
            "def test_contract():\n    assert True\n", encoding="utf-8"
        )
        (self.root / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "child_holder.py").write_text(CHILD_SCRIPT, encoding="utf-8")
        subprocess.run(
            [
                "git",
                "add",
                "locked.txt",
                "acceptance_test.py",
                "product.py",
                "child_holder.py",
            ],
            cwd=self.root,
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _reserve_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_timeout_kills_process_tree_and_releases_port(self) -> None:
        port = self._reserve_port()
        manifest = {
            "schema_version": 1,
            "stage": 0,
            "name": "process-cleanup",
            "required_documents": ["locked.txt"],
            "allowed_paths": ["product.py"],
            "forbidden_paths": ["never/**"],
            "preserved_paths": ["locked.txt"],
            "required_paths": ["product.py"],
            "forbidden_symbols": [],
            "locked_paths": ["locked.txt", "manifest.json"],
            "locked_acceptance_paths": ["acceptance_test.py"],
            "commands": [
                {
                    "id": "holder",
                    "cwd": ".",
                    "argv": ["{python}", "child_holder.py", str(port)],
                    "timeout_seconds": 0.3,
                }
            ],
            "git_diff_check": False,
            "gates": [
                {
                    "id": "automated",
                    "mode": "automated",
                    "description": "auto",
                    "checks": [
                        "required_documents",
                        "required_paths",
                        "preserved_paths",
                        "manifest_locked",
                        "locked_files",
                        "locked_acceptance_files",
                        "changed_paths_allowed",
                        "forbidden_paths",
                        "forbidden_symbols",
                        "command:holder",
                    ],
                }
            ],
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        verifier = StageVerifier(self.root, manifest, path)
        verifier.record_baseline(review_key="secret")
        result = verifier.verify()
        command = next(c for c in result.checks if c.check_id == "command:holder")
        self.assertEqual("FAIL", command.status)
        self.assertIn("timeout", command.summary)

        # Port must become bindable again within a short window after tree kill.
        deadline = time.time() + 5.0
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("127.0.0.1", port))
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        else:
            self.fail(f"port {port} still not reusable after process-tree kill: {last_error}")


if __name__ == "__main__":
    unittest.main()
