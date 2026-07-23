"""
可选运行归档（RunArchiver）

默认关闭。开启后在 ``<UserDataDir>/DataFactory/run_history/<session-id>/`` 创建：
    metadata.json   会话信息、project/runtime revision、记录 tag、采样时间
    values.sqlite   真实运行值（仅选定 tag）
    alarms.jsonl    报警事件与用户写入审计事件

不记录全部位号；只记录用户选定或 display=true 的 tag。
不持久化 force 状态；可记录"发生过强制操作"审计事件，但重启后不恢复强制。
归档失败不得影响 Engine 实时运行（由调用方 try/except 包裹）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class RunArchiver:
    def __init__(self, base_dir: str, session_id: str, metadata: Dict[str, Any], tags: List[str]):
        self._dir = Path(base_dir) / session_id
        self._session_id = session_id
        self._metadata = metadata
        self._tags = list(tags)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._alarms_path = self._dir / "alarms.jsonl"
        self._closed = False

    def start(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        meta = dict(self._metadata)
        meta.setdefault("sessionId", self._session_id)
        meta.setdefault("tags", self._tags)
        meta.setdefault("startedAt", _now_iso())
        with (self._dir / "metadata.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self._conn = sqlite3.connect(str(self._dir / "values.sqlite"))
        cols = ", ".join(f'"{t}" REAL' for t in self._tags)
        self._conn.execute(
            f'CREATE TABLE IF NOT EXISTS samples (sim_time REAL, received_at REAL{", " + cols if cols else ""})'
        )
        self._conn.commit()

    def record(self, snapshot: Dict[str, Any], sim_time: Optional[float]) -> None:
        if self._closed or self._conn is None:
            return
        with self._lock:
            values = []
            for t in self._tags:
                v = snapshot.get(t)
                values.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
            cols = ", ".join(f'"{t}"' for t in self._tags)
            placeholders = ", ".join("?" for _ in self._tags)
            sql = f'INSERT INTO samples (sim_time, received_at{", " + cols if cols else ""}) VALUES (?, ?{", " + placeholders if placeholders else ""})'
            self._conn.execute(sql, [sim_time, time.time(), *values])
            self._conn.commit()

    def record_event(self, kind: str, event: Dict[str, Any]) -> None:
        if self._closed:
            return
        with self._lock:
            line = json.dumps({"kind": kind, "time": _now_iso(), **event}, ensure_ascii=False)
            with self._alarms_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._conn is not None:
                try:
                    self._conn.commit()
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


class RunHistory:
    """管理 run_history 目录下的历史运行。"""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def list_runs(self) -> List[Dict[str, Any]]:
        if not self.base_dir.exists():
            return []
        out = []
        for entry in sorted(self.base_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            meta_path = entry / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            out.append(meta)
        return out

    def read_values(self, session_id: str, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        db = self.base_dir / session_id / "values.sqlite"
        if not db.exists():
            return []
        conn = sqlite3.connect(str(db))
        try:
            cur = conn.execute("SELECT * FROM samples ORDER BY rowid")
            cols = [d[0] for d in cur.description]
            rows = []
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                if tags:
                    keep = {"sim_time", "received_at"} | set(tags)
                    rec = {k: v for k, v in rec.items() if k in keep}
                rows.append(rec)
            return rows
        finally:
            conn.close()

    def export_csv(self, session_id: str, output_path: str) -> int:
        import csv
        rows = self.read_values(session_id)
        if not rows:
            return 0
        cols = list(rows[0].keys())
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def delete_run(self, session_id: str) -> bool:
        import shutil
        target = self.base_dir / session_id
        if not target.exists():
            return False
        # 防止路径穿越：确保 target 在 base_dir 内
        if target.resolve().parent != self.base_dir.resolve():
            return False
        shutil.rmtree(target, ignore_errors=True)
        return True

    def disk_usage_bytes(self) -> int:
        if not self.base_dir.exists():
            return 0
        total = 0
        for p in self.base_dir.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total
