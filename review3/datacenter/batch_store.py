"""
Batch SQLite 存储层。

每个 batch 任务独立一个 SQLite 文件，存储在：
    %LOCALAPPDATA%/DataFactory/batch_runs/<batchId>/data.sqlite

表结构（动态列）：
    CREATE TABLE samples (
        cycle_index  INTEGER,
        sim_time     REAL,
        need_sample  INTEGER,
        <tag1>       REAL,
        <tag2>       REAL,
        ...
    )

写入策略：每 500 行提交一次事务，避免内存堆积。
读取策略：按 offset/limit 分页读取；导出时用 cursor 逐行流式读取。
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from components.utils.logger import get_logger

logger = get_logger("batch_store")

_BATCH_INSERT_BATCH_SIZE = 500


def _batch_root() -> Path:
    """返回 batch_runs 根目录：%LOCALAPPDATA%/DataFactory/batch_runs"""
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    root = Path(local) / "DataFactory" / "batch_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def batch_dir(batch_id: str) -> Path:
    """返回单个 batch 任务目录。"""
    return _batch_root() / batch_id


def list_batch_dirs() -> List[Path]:
    """列出所有 batch 目录。"""
    root = _batch_root()
    if not root.exists():
        return []
    return [d for d in root.iterdir() if d.is_dir()]


def _quote_ident(name: str) -> str:
    """SQLite identifier quoting：用双引号包裹，内部双引号转义为两个双引号。"""
    return '"' + name.replace('"', '""') + '"'


class BatchStore:
    """单个 batch 任务的 SQLite 存储。"""

    def __init__(self, batch_id: str, columns: Optional[List[str]] = None) -> None:
        self.batch_id = batch_id
        self.dir = batch_dir(batch_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "data.sqlite"
        self.meta_path = self.dir / "meta.json"
        self._conn: Optional[sqlite3.Connection] = None
        self._columns: List[str] = list(columns) if columns else []
        self._buffer: List[tuple] = []
        self._cycles_completed = 0

    # ------------------------------------------------------------------ #
    # 生命周期                                                            #
    # ------------------------------------------------------------------ #

    def open(self) -> None:
        """打开数据库连接（用于写入）。"""
        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # 手动事务
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        """关闭连接，刷入剩余缓冲。"""
        self._flush()
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ #
    # 写入                                                                #
    # ------------------------------------------------------------------ #

    def init_table(self, signal_keys: List[str]) -> None:
        """根据信号列名创建表。signal_keys 不含元数据字段。"""
        self._columns = list(signal_keys)
        cols_def = ["cycle_index INTEGER", "sim_time REAL", "need_sample INTEGER"]
        for k in signal_keys:
            cols_def.append(f'"{k}" REAL')
        sql = f"CREATE TABLE IF NOT EXISTS samples ({', '.join(cols_def)})"
        assert self._conn is not None
        self._conn.execute(sql)

    def add_row(self, cycle_index: int, sim_time: float, need_sample: bool,
                values: Dict[str, Any]) -> None:
        """添加一行数据到缓冲，满 _BATCH_INSERT_BATCH_SIZE 时自动提交。"""
        row = [cycle_index, sim_time, 1 if need_sample else 0]
        for k in self._columns:
            v = values.get(k)
            row.append(v if isinstance(v, (int, float)) else None)
        self._buffer.append(tuple(row))
        self._cycles_completed += 1
        if len(self._buffer) >= _BATCH_INSERT_BATCH_SIZE:
            self._flush()

    def _flush(self) -> None:
        """将缓冲区写入数据库。"""
        if not self._buffer or self._conn is None:
            return
        placeholders = ",".join("?" * (3 + len(self._columns)))
        col_names = "cycle_index, sim_time, need_sample, " + ", ".join(f'"{k}"' for k in self._columns)
        sql = f"INSERT INTO samples ({col_names}) VALUES ({placeholders})"
        try:
            self._conn.execute("BEGIN")
            self._conn.executemany(sql, self._buffer)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._buffer.clear()

    # ------------------------------------------------------------------ #
    # 读取                                                                #
    # ------------------------------------------------------------------ #

    def read_rows(self, offset: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        """分页读取行（用于预览）。返回前端期望的 row 格式。"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            base_cols = "cycle_index, sim_time, need_sample"
            if self._columns:
                dyn_cols = ", ".join(_quote_ident(k) for k in self._columns)
                sql = f"SELECT {base_cols}, {dyn_cols} FROM samples ORDER BY cycle_index LIMIT ? OFFSET ?"
            else:
                sql = f"SELECT {base_cols} FROM samples ORDER BY cycle_index LIMIT ? OFFSET ?"
            rows = conn.execute(sql, (limit, offset)).fetchall()
            result = []
            for row in rows:
                d: Dict[str, Any] = {
                    "_cycle": row[0],
                    "_sim_time": row[1],
                    "_need_sample": bool(row[2]),
                }
                for i, k in enumerate(self._columns):
                    d[k] = row[3 + i]
                result.append(d)
            return result
        finally:
            conn.close()

    def count_rows(self) -> int:
        """总行数。"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            return conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        finally:
            conn.close()

    def count_sampled_rows(self) -> int:
        """need_sample=True 行数。"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            return conn.execute("SELECT COUNT(*) FROM samples WHERE need_sample=1").fetchone()[0]
        finally:
            conn.close()

    def iter_sampled_rows(self) -> Iterator[Dict[str, Any]]:
        """流式迭代采样行（用于导出）。逐行 yield，不加载全部到内存。"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            base_cols = "cycle_index, sim_time, need_sample"
            if self._columns:
                dyn_cols = ", ".join(_quote_ident(k) for k in self._columns)
                sql = f"SELECT {base_cols}, {dyn_cols} FROM samples WHERE need_sample=1 ORDER BY cycle_index"
            else:
                sql = f"SELECT {base_cols} FROM samples WHERE need_sample=1 ORDER BY cycle_index"
            cursor = conn.execute(sql)
            for row in cursor:
                d: Dict[str, Any] = {
                    "sim_time": row[1],
                    "need_sample": True,
                }
                for i, k in enumerate(self._columns):
                    d[k] = row[3 + i]
                yield d
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # meta.json                                                           #
    # ------------------------------------------------------------------ #

    def save_meta(self, meta: Dict[str, Any]) -> None:
        """原子写入 meta.json（先写临时文件再 os.replace）。"""
        meta["updatedAt"] = datetime.now(timezone.utc).isoformat()
        tmp = self.meta_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.meta_path)

    def load_meta(self) -> Optional[Dict[str, Any]]:
        """读取 meta.json。"""
        if not self.meta_path.exists():
            return None
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @property
    def cycles_completed(self) -> int:
        return self._cycles_completed

    @property
    def columns(self) -> List[str]:
        return list(self._columns)


# ---------------------------------------------------------------------- #
# 模块级辅助函数                                                          #
# ---------------------------------------------------------------------- #

def load_meta_for(batch_id: str) -> Optional[Dict[str, Any]]:
    """读取指定 batch 的 meta.json。"""
    p = batch_dir(batch_id) / "meta.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_batch_dir(batch_id: str) -> None:
    """删除 batch 目录（含 data.sqlite + meta.json）。"""
    import shutil
    d = batch_dir(batch_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        logger.info("deleted batch dir: %s", d)
