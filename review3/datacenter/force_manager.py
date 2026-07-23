"""
输出强制管理器（OutputForceManager）

职责：
- 维护每个位号的强制状态（follow / hold / zero / fixed）
- 线程安全：FastAPI 线程写，OPC UA 轮询线程读
- 位号合法性校验：只允许对实际发布到 UA 的数值位号强制
- hold 原子捕获：在锁内读取当前运行值冻结
- 持续时间：到期自动恢复 follow

强制只影响 UA 输出读取，不影响引擎计算与外部写入。
强制状态属于运行会话，不持久化。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Set

VALID_MODES = ("follow", "hold", "zero", "fixed")


class ForceError(Exception):
    pass


class ForceManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._forces: Dict[str, dict] = {}
        self._valid_tags: Optional[Set[str]] = None
        self._runtime_ref: Optional[Dict[str, float]] = None

    def bind_runtime(self, shared_data: Dict[str, float]) -> None:
        """绑定运行内存引用，供 hold 原子捕获当前值。"""
        self._runtime_ref = shared_data

    def set_valid_tags(self, tags: Set[str]) -> None:
        """设置权威可发布位号集合（数值型）。"""
        with self._lock:
            self._valid_tags = set(tags)

    def _is_valid_tag(self, tag: str) -> bool:
        if self._valid_tags is None:
            return True
        return tag in self._valid_tags

    def set_force(
        self,
        tag: str,
        mode: str,
        value: Optional[float] = None,
        duration: Optional[float] = None,
    ) -> dict:
        if mode not in VALID_MODES:
            raise ForceError(f"无效模式: {mode}")
        with self._lock:
            if not self._is_valid_tag(tag):
                raise ForceError(f"位号不存在或非数值位号: {tag}")

            if mode == "follow":
                self._forces.pop(tag, None)
                return {"mode": "follow"}

            entry: dict = {"mode": mode}

            if mode == "hold":
                if value is not None:
                    entry["value"] = float(value)
                else:
                    cur = self._runtime_ref.get(tag) if self._runtime_ref else None
                    entry["value"] = float(cur) if isinstance(cur, (int, float)) else 0.0
            elif mode == "fixed":
                if value is None:
                    raise ForceError("fixed 模式必须提供 value")
                fv = float(value)
                if fv != fv or fv in (float("inf"), float("-inf")):
                    raise ForceError("fixed 值必须是有限数")
                entry["value"] = fv

            if duration is not None and duration > 0:
                entry["expires_at"] = time.time() + float(duration)

            self._forces[tag] = entry
            return dict(entry)

    def clear_force(self, tag: str) -> None:
        with self._lock:
            self._forces.pop(tag, None)

    def clear_all(self) -> None:
        with self._lock:
            self._forces.clear()

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [t for t, e in self._forces.items()
                   if isinstance(e.get("expires_at"), (int, float)) and e["expires_at"] <= now]
        for t in expired:
            del self._forces[t]

    def snapshot(self) -> Dict[str, dict]:
        """返回当前有效强制状态的副本（清理已过期项）。"""
        with self._lock:
            self._purge_expired_locked()
            return {t: dict(e) for t, e in self._forces.items()}

    def apply(self, params: Dict[str, float]) -> Dict[str, float]:
        """
        基于运行值 params 计算 UA 输出值，返回新 dict。
        OPC UA 轮询每轮调用一次，只在锁内读取强制快照。
        """
        with self._lock:
            self._purge_expired_locked()
            forces = {t: dict(e) for t, e in self._forces.items()}

        out = dict(params)
        for tag, entry in forces.items():
            mode = entry.get("mode", "follow")
            if mode == "zero":
                out[tag] = 0.0
            elif mode in ("hold", "fixed"):
                out[tag] = float(entry.get("value", 0.0))
        return out
