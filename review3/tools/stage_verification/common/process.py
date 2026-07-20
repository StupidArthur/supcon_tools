"""Process-tree termination and ManagedProcess for acceptance harnesses."""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Tunables for ManagedProcess stop / ready polling.
DEFAULT_GRACEFUL_STOP_SECONDS = 2.0
DEFAULT_READY_POLL_SECONDS = 0.05
DEFAULT_OUTPUT_TAIL_CHARS = 8000


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


@dataclass
class ManagedProcess:
    """Context-managed child process with forced cleanup on exit.

    Public methods: start, wait_ready, stdout_tail, stop, assert_stopped.
    """

    argv: Sequence[str]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    graceful_stop_seconds: float = DEFAULT_GRACEFUL_STOP_SECONDS
    output_tail_chars: int = DEFAULT_OUTPUT_TAIL_CHARS
    _process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _output_chunks: list[str] = field(default_factory=list, init=False, repr=False)
    _output_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _reader: threading.Thread | None = field(default=None, init=False, repr=False)
    exit_code: int | None = field(default=None, init=False)

    @classmethod
    def start(
        cls,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        graceful_stop_seconds: float = DEFAULT_GRACEFUL_STOP_SECONDS,
    ) -> "ManagedProcess":
        """Spawn a managed process and return the wrapper."""
        managed = cls(
            argv=list(argv),
            cwd=Path(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            graceful_stop_seconds=graceful_stop_seconds,
        )
        managed._spawn()
        return managed

    def _spawn(self) -> None:
        if self._process is not None:
            raise RuntimeError("ManagedProcess already started")
        environment = os.environ.copy()
        if self.env:
            environment.update(self.env)
        environment.pop("STAGE_VERIFICATION_REVIEW_KEY", None)
        popen_kwargs: dict[str, Any] = {}
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        self._process = subprocess.Popen(
            list(self.argv),
            cwd=str(self.cwd) if self.cwd is not None else None,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            **popen_kwargs,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            for line in self._process.stdout:
                with self._output_lock:
                    self._output_chunks.append(line)
        except (ValueError, OSError):
            return

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def wait_ready(
        self,
        predicate: Callable[["ManagedProcess"], bool],
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = DEFAULT_READY_POLL_SECONDS,
    ) -> None:
        """Poll *predicate(self)* until true; fail fast if the process exits."""
        if self._process is None:
            raise RuntimeError("ManagedProcess has not been started")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self._join_reader()
                raise RuntimeError(
                    f"Process exited before ready (code={self._process.returncode}): "
                    f"{' '.join(self.argv)}\n{self.stdout_tail()}"
                )
            if predicate(self):
                return
            time.sleep(poll_interval_seconds)
        raise TimeoutError(
            f"Process not ready within {timeout_seconds:.1f}s: {' '.join(self.argv)}"
        )

    def _join_reader(self) -> None:
        if self._reader is not None:
            self._reader.join(timeout=2.0)

    def stdout_tail(self, limit: int | None = None) -> str:
        """Return the trailing captured stdout/stderr text."""
        with self._output_lock:
            text = "".join(self._output_chunks)
        size = self.output_tail_chars if limit is None else limit
        return text[-size:]

    def stop(self) -> int | None:
        """Gracefully terminate, then force-kill the process tree if needed."""
        if self._process is None:
            return self.exit_code
        if self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass
            try:
                self._process.wait(timeout=self.graceful_stop_seconds)
            except subprocess.TimeoutExpired:
                terminate_process_tree(self._process)
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
        self._join_reader()
        self.exit_code = self._process.returncode
        return self.exit_code

    def assert_stopped(self) -> None:
        """Raise if the process still appears running."""
        if self.is_running():
            raise AssertionError(
                f"ManagedProcess still running (pid={self.pid}): {' '.join(self.argv)}"
            )

    def __enter__(self) -> "ManagedProcess":
        if self._process is None:
            self._spawn()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
        self.assert_stopped()
