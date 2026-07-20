"""Tests for ManagedProcess cleanup and stdout capture."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

from tools.stage_verification.common.process import ManagedProcess


class ManagedProcessTests(unittest.TestCase):
    def test_context_manager_stops_process(self) -> None:
        with ManagedProcess.start(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        ) as proc:
            self.assertTrue(proc.is_running())
        proc.assert_stopped()

    def test_wait_ready_succeeds_on_predicate(self) -> None:
        marker = "READY_MARK"
        proc = ManagedProcess.start(
            [
                sys.executable,
                "-c",
                "import time; print('warmup', flush=True); time.sleep(0.2); "
                f"print({marker!r}, flush=True); time.sleep(30)",
            ]
        )
        try:
            proc.wait_ready(
                lambda p: marker in p.stdout_tail(),
                timeout_seconds=5.0,
            )
            self.assertIn(marker, proc.stdout_tail())
        finally:
            proc.stop()
            proc.assert_stopped()

    def test_reviewer_key_not_inherited(self) -> None:
        with patch.dict(os.environ, {"STAGE_VERIFICATION_REVIEW_KEY": "secret"}):
            proc = ManagedProcess.start(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; sys.exit(9 if os.getenv('STAGE_VERIFICATION_REVIEW_KEY') else 0)",
                ]
            )
            try:
                deadline = time.time() + 5.0
                while proc.is_running() and time.time() < deadline:
                    time.sleep(0.05)
                code = proc.stop()
                self.assertEqual(0, code)
            finally:
                proc.assert_stopped()


if __name__ == "__main__":
    unittest.main()
