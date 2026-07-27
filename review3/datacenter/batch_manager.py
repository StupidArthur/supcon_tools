"""
Batch 任务管理器。

职责：
- 异步启动 batch 仿真（后台线程执行 engine.step() 循环）
- 实时写入 SQLite（不在内存中保存全部结果）
- 管理 meta.json（任务状态原子更新）
- 取消、删除、导出
- 清理旧 batch 目录（只保留最近一次成功结果）
- 程序启动时扫描 interrupted 任务

并发规则：
- 一次只能运行一个 batch
- 实时仿真运行时禁止 batch
- batch 运行时禁止启动实时仿真
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from components.utils.logger import get_logger

from .batch_store import (
    BatchStore,
    batch_dir,
    delete_batch_dir,
    list_batch_dirs,
    load_meta_for,
)

logger = get_logger("batch_manager")

# 任务状态
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"

_EXCLUDED_SNAPSHOT_FIELDS = {
    "cycle_count", "need_sample", "sim_time", "time_str", "exec_ratio",
    "_consecutive_failures", "_safe_state",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_hash(config_path: str) -> str:
    """计算配置文件 SHA-256。"""
    h = hashlib.sha256()
    with open(config_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class BatchManager:
    """单例 batch 任务管理器。"""

    _instance: Optional["BatchManager"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "BatchManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_batch_id: Optional[str] = None
        self._cancel_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._runtime_check_fn: Optional[callable] = None

    def set_runtime_check(self, fn: callable) -> None:
        """注入实时运行状态检查函数：返回 True 表示实时正在运行。"""
        self._runtime_check_fn = fn

    # ------------------------------------------------------------------ #
    # 启动                                                                #
    # ------------------------------------------------------------------ #

    def start_batch(
        self,
        config_path: str,
        cycles: int,
        cycle_time: Optional[float] = None,
    ) -> str:
        """异步启动 batch，返回 batchId。

        处理顺序（§三）：
        1. 创建 batchId 和目录
        2. 解析配置
        3. 成功创建 Engine
        4. 状态改为 running
        5. 删除旧 batch 目录
        6. 开始执行

        如果步骤 2/3 失败，旧结果保留。
        """
        with self._lock:
            if self._current_batch_id is not None:
                raise BatchConflictError("已有批量任务正在运行")
            if self._runtime_check_fn and self._runtime_check_fn():
                raise BatchConflictError("实时运行中，禁止批量任务")

        import os
        if not os.path.isfile(config_path):
            raise BatchValidationError(f"config 文件不存在: {config_path}")
        if cycles <= 0:
            raise BatchValidationError("cycles 必须大于 0")

        batch_id = f"b_{uuid4().hex[:16]}"
        store = BatchStore(batch_id)
        config_hash = _config_hash(config_path)

        # 写入初始 meta（status=queued）
        meta = {
            "batchId": batch_id,
            "status": STATUS_QUEUED,
            "configPath": config_path,
            "configHash": config_hash,
            "cyclesRequested": cycles,
            "cyclesCompleted": 0,
            "columns": [],
            "displayColumns": [],
            "plotScales": {},
            "createdAt": _now_iso(),
            "startedAt": None,
            "finishedAt": None,
            "error": None,
        }
        store.save_meta(meta)

        # 启动后台线程（线程内完成配置解析、Engine 创建、状态切换）
        with self._lock:
            self._current_batch_id = batch_id
            self._cancel_event = threading.Event()

        self._thread = threading.Thread(
            target=self._run_batch_thread,
            args=(batch_id, config_path, cycles, cycle_time),
            daemon=True,
        )
        self._thread.start()
        return batch_id

    # ------------------------------------------------------------------ #
    # 后台线程                                                            #
    # ------------------------------------------------------------------ #

    def _run_batch_thread(
        self,
        batch_id: str,
        config_path: str,
        cycles: int,
        cycle_time: Optional[float],
    ) -> None:
        """batch 执行线程。"""
        store = BatchStore(batch_id)
        thread_error: Optional[str] = None

        try:
            # 解析配置 + 创建 Engine（失败则旧结果保留）
            from controller.engine import UnifiedEngine
            from controller.parser import DSLParser
            from controller.clock import ClockMode

            parser = DSLParser()
            config = parser.parse_file(config_path)
            engine = UnifiedEngine.from_program_config(config)
            engine.clock.config.mode = ClockMode.GENERATOR
            if cycle_time is not None and cycle_time > 0:
                engine.clock.config.cycle_time = cycle_time

            # Engine 创建成功 → 状态改为 running → 删除旧 batch
            meta = store.load_meta() or {}
            meta["status"] = STATUS_RUNNING
            meta["startedAt"] = _now_iso()
            store.save_meta(meta)

            # 删除旧 batch 目录（保留当前 batch_id）
            self._cleanup_old_batches(batch_id)

            # 执行仿真循环
            store.open()
            engine.clock.start()
            signal_keys: List[str] = []
            table_inited = False

            try:
                for i in range(cycles):
                    if self._cancel_event and self._cancel_event.is_set():
                        meta = store.load_meta() or {}
                        meta["status"] = STATUS_CANCELLED
                        meta["finishedAt"] = _now_iso()
                        store.save_meta(meta)
                        store.close()
                        with self._lock:
                            self._current_batch_id = None
                            self._cancel_event = None
                        return

                    snapshot = engine.step()

                    # 首步后确定列并建表
                    if not table_inited:
                        signal_keys = sorted(
                            k for k in snapshot.keys()
                            if k not in _EXCLUDED_SNAPSHOT_FIELDS
                        )
                        store.init_table(signal_keys)
                        table_inited = True

                    sim_time = snapshot.get("sim_time", 0.0)
                    need_sample = bool(snapshot.get("need_sample", False))
                    store.add_row(i, sim_time, need_sample, snapshot)

                    # 每 1000 周期更新 meta
                    if (i + 1) % 1000 == 0:
                        meta = store.load_meta() or {}
                        meta["cyclesCompleted"] = i + 1
                        store.save_meta(meta)

            finally:
                engine.clock.stop()
                store.close()

            # 完成：写入最终 meta
            display_columns = engine.get_display_variables()
            all_plot_scales = engine.get_plot_scales()
            plot_scales = {
                col: all_plot_scales[col]
                for col in display_columns
                if col in all_plot_scales
            }
            final_meta = store.load_meta() or {}
            final_meta["status"] = STATUS_COMPLETED
            final_meta["cyclesCompleted"] = cycles
            final_meta["columns"] = signal_keys
            final_meta["displayColumns"] = display_columns
            final_meta["plotScales"] = plot_scales
            final_meta["finishedAt"] = _now_iso()
            store.save_meta(final_meta)

        except Exception as e:
            logger.exception("batch thread failed: %s", batch_id)
            thread_error = str(e)
            try:
                meta = store.load_meta() or {}
                meta["status"] = STATUS_FAILED
                meta["error"] = thread_error
                meta["finishedAt"] = _now_iso()
                store.save_meta(meta)
            except Exception:
                pass
        finally:
            with self._lock:
                if self._current_batch_id == batch_id:
                    self._current_batch_id = None
                    self._cancel_event = None

    # ------------------------------------------------------------------ #
    # 查询                                                                #
    # ------------------------------------------------------------------ #

    def get_status(self, batch_id: str) -> Dict[str, Any]:
        """返回任务状态。"""
        meta = load_meta_for(batch_id)
        if meta is None:
            raise BatchNotFoundError(f"batch 不存在: {batch_id}")
        return {
            "ok": True,
            "batchId": batch_id,
            "status": meta.get("status", "unknown"),
            "cyclesRequested": meta.get("cyclesRequested", 0),
            "cyclesCompleted": meta.get("cyclesCompleted", 0),
            "columns": meta.get("columns", []),
            "displayColumns": meta.get("displayColumns", []),
            "plotScales": meta.get("plotScales", {}),
            "error": meta.get("error"),
        }

    def get_rows(self, batch_id: str, offset: int = 0, limit: int = 200) -> Dict[str, Any]:
        """分页读取预览行。"""
        meta = load_meta_for(batch_id)
        if meta is None:
            raise BatchNotFoundError(f"batch 不存在: {batch_id}")
        if limit <= 0:
            limit = 200
        if limit > 1000:
            limit = 1000
        if offset < 0:
            offset = 0
        store = BatchStore(batch_id, columns=meta.get("columns", []))
        rows = store.read_rows(offset, limit)
        total = store.count_rows()
        return {
            "ok": True,
            "batchId": batch_id,
            "rows": rows,
            "offset": offset,
            "limit": limit,
            "total": total,
        }

    # ------------------------------------------------------------------ #
    # 取消                                                                #
    # ------------------------------------------------------------------ #

    def cancel(self, batch_id: str) -> Dict[str, Any]:
        """取消正在运行的任务。"""
        with self._lock:
            if self._current_batch_id != batch_id:
                raise BatchConflictError("任务不在运行中或不存在")
            if self._cancel_event:
                self._cancel_event.set()
        return {"ok": True, "batchId": batch_id, "status": STATUS_CANCELLED}

    # ------------------------------------------------------------------ #
    # 删除                                                                #
    # ------------------------------------------------------------------ #

    def delete(self, batch_id: str) -> Dict[str, Any]:
        """删除 batch 结果（不得删除正在运行的任务）。"""
        with self._lock:
            if self._current_batch_id == batch_id:
                raise BatchConflictError("任务正在运行，无法删除")
        meta = load_meta_for(batch_id)
        if meta is None:
            raise BatchNotFoundError(f"batch 不存在: {batch_id}")
        if meta.get("status") == STATUS_RUNNING:
            raise BatchConflictError("任务正在运行，无法删除")
        delete_batch_dir(batch_id)
        return {"ok": True, "batchId": batch_id}

    # ------------------------------------------------------------------ #
    # 导出                                                                #
    # ------------------------------------------------------------------ #

    def export(
        self,
        batch_id: str,
        columns: List[str],
        export_path: str,
        fmt: str,
        sheet_name: str = "",
    ) -> Dict[str, Any]:
        """从 SQLite 流式导出。"""
        meta = load_meta_for(batch_id)
        if meta is None:
            raise BatchNotFoundError(f"batch 不存在: {batch_id}")
        if meta.get("status") == STATUS_RUNNING:
            raise BatchConflictError("任务正在运行，无法导出")

        store = BatchStore(batch_id, columns=meta.get("columns", []))
        all_columns = meta.get("columns", [])
        if not columns:
            columns = all_columns
        # 过滤为实际存在的列
        columns = [c for c in columns if c in all_columns]
        if not columns:
            raise BatchValidationError("没有可导出的列")

        # 使用临时文件导出，成功后 os.replace
        import os
        tmp_path = export_path + ".tmp"
        fmt_lower = (fmt or "csv").lower()

        if fmt_lower == "csv":
            row_count = self._export_csv(store, columns, tmp_path, meta)
        elif fmt_lower == "xlsx":
            row_count = self._export_xlsx(store, columns, tmp_path, meta, sheet_name)
        else:
            raise BatchValidationError(f"不支持的导出格式: {fmt}")

        os.replace(tmp_path, export_path)
        logger.info("export done: %s, %d rows -> %s", batch_id, row_count, export_path)
        return {
            "ok": True,
            "batchId": batch_id,
            "path": export_path,
            "rows": row_count,
            "format": fmt_lower,
        }

    def _export_csv(
        self,
        store: BatchStore,
        columns: List[str],
        output_path: str,
        meta: Dict[str, Any],
    ) -> int:
        """流式 CSV 导出：cursor 逐行读取，不构造完整列表。"""
        import csv
        from components.export_templates import TemplateManager

        template = TemplateManager().load_template("prediction")
        time_col = template.time_column_name
        time_fmt = template.time_format

        from datetime import datetime as _dt

        count = 0
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # 第一行表头
            writer.writerow([time_col] + columns)
            # 第二行描述
            if template.header_rows == 2:
                from components.export_templates.template_manager import (
                    DEFAULT_TIME_DESCRIPTION,
                    DEFAULT_PARAM_DESCRIPTION,
                )
                writer.writerow([DEFAULT_TIME_DESCRIPTION] + [DEFAULT_PARAM_DESCRIPTION] * len(columns))
            # 数据行
            for snap in store.iter_sampled_rows():
                sim_time = snap.get("sim_time", 0.0)
                time_str = _dt.fromtimestamp(float(sim_time)).strftime(time_fmt)
                row = [time_str]
                for col in columns:
                    v = snap.get(col)
                    row.append("" if v is None else str(v))
                writer.writerow(row)
                count += 1
        return count

    def _export_xlsx(
        self,
        store: BatchStore,
        columns: List[str],
        output_path: str,
        meta: Dict[str, Any],
        sheet_name: str,
    ) -> int:
        """流式 XLSX 导出：使用 openpyxl write_only 模式。"""
        from openpyxl import Workbook
        from components.export_templates import TemplateManager
        from components.export_templates.template_manager import (
            DEFAULT_TIME_DESCRIPTION,
            DEFAULT_PARAM_DESCRIPTION,
        )
        from datetime import datetime as _dt

        template = TemplateManager().load_template("prediction")
        sn = (sheet_name or template.sheet_name or "控制器")[:31]

        wb = Workbook(write_only=True)
        ws = wb.create_sheet(sn)

        # 第一行表头
        ws.append([template.time_column_name] + columns)
        # 第二行描述
        if template.header_rows == 2:
            ws.append([DEFAULT_TIME_DESCRIPTION] + [DEFAULT_PARAM_DESCRIPTION] * len(columns))

        time_fmt = template.time_format
        count = 0
        for snap in store.iter_sampled_rows():
            sim_time = snap.get("sim_time", 0.0)
            time_str = _dt.fromtimestamp(float(sim_time)).strftime(time_fmt)
            row = [time_str]
            for col in columns:
                v = snap.get(col)
                row.append("" if v is None else v)
            ws.append(row)
            count += 1

        wb.save(output_path)
        return count

    # ------------------------------------------------------------------ #
    # 清理                                                                #
    # ------------------------------------------------------------------ #

    def _cleanup_old_batches(self, except_batch_id: str) -> None:
        """删除所有旧 batch 目录（保留当前 batch_id）。

        不删除正在运行的任务（理论上只有当前 batch 在运行）。
        不删除用户导出的 CSV/XLSX 文件（那些不在 batch 目录内）。
        """
        for d in list_batch_dirs():
            if d.name == except_batch_id:
                continue
            # 检查是否正在运行（防御性，理论上不会有其他运行中的 batch）
            meta = load_meta_for(d.name)
            if meta and meta.get("status") == STATUS_RUNNING:
                continue
            delete_batch_dir(d.name)

    # ------------------------------------------------------------------ #
    # 启动扫描                                                            #
    # ------------------------------------------------------------------ #

    def startup_scan(self) -> None:
        """程序启动时扫描 batch 目录，将 status=running 改为 interrupted。

        首版不实现断点续跑。
        """
        for d in list_batch_dirs():
            meta = load_meta_for(d.name)
            if meta and meta.get("status") == STATUS_RUNNING:
                meta["status"] = STATUS_INTERRUPTED
                meta["error"] = "服务重启，任务被中断"
                meta["finishedAt"] = _now_iso()
                store = BatchStore(d.name)
                store.save_meta(meta)
                logger.info("startup_scan: marked %s as interrupted", d.name)


# ---------------------------------------------------------------------- #
# 异常类型                                                                #
# ---------------------------------------------------------------------- #

class BatchConflictError(Exception):
    """并发冲突（409）。"""


class BatchValidationError(Exception):
    """参数校验失败（400）。"""


class BatchNotFoundError(Exception):
    """batch 不存在（404）。"""
