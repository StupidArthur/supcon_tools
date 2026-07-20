"""Process-tree termination helpers used when manifest commands time out."""

from __future__ import annotations

import os
import platform
import signal
import subprocess
from typing import Any


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    """Force-kill *process* and every descendant.

    On Windows this uses ``taskkill /T /F``. On POSIX it sends SIGKILL to the
    process group created with ``start_new_session=True``.
    """
    if process.poll() is not None:
        return
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass
