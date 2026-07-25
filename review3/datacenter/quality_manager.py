"""
质量码覆盖管理器（QualityManager）

职责：
- 维护每个位号的质量码覆盖状态（None / Good / Uncertain / Bad）。
- 线程安全：FastAPI 线程写，OPC UA 轮询线程读。
- 位号合法性校验：只允许对实际发布到 UA 的数值位号覆盖。
- 与 fixed 模式彼此独立：同一个 tag 可以同时固定值和覆盖质量码。

状态只在当前进程内存在，不写入任何持久化文件。
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Set


class QualityError(Exception):
    pass


# 大小写不敏感：客户端可发送 "good" / "Good" / "GOOD"。
_VALID_QUALITIES = {"good", "uncertain", "bad"}


def normalize_quality(quality: str) -> str:
    if not isinstance(quality, str):
        raise QualityError(f"无效 quality 类型: {type(quality).__name__}")
    q = quality.strip()
    low = q.lower()
    if low not in _VALID_QUALITIES:
        raise QualityError(f"无效 quality: {quality!r}; 必须是 Good / Uncertain / Bad")
    if low == "good":
        return "Good"
    if low == "uncertain":
        return "Uncertain"
    return "Bad"


class QualityManager:
    """质量码覆盖状态管理。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._qualities: Dict[str, str] = {}
        self._valid_tags: Optional[Set[str]] = None

    def set_valid_tags(self, tags: Set[str]) -> None:
        with self._lock:
            self._valid_tags = set(tags)

    def snapshot_valid_tags(self) -> Set[str]:
        with self._lock:
            return set(self._valid_tags) if self._valid_tags is not None else set()

    def _is_valid_tag(self, tag: str) -> bool:
        if self._valid_tags is None:
            return True
        return tag in self._valid_tags

    def set_quality(self, tag: str, quality: str) -> str:
        q = normalize_quality(quality)
        with self._lock:
            if not self._is_valid_tag(tag):
                raise QualityError(f"位号不存在或非数值位号: {tag}")
            if q == "Good":
                # 显式 Good = 清除覆盖
                self._qualities.pop(tag, None)
                return "Good"
            self._qualities[tag] = q
            return q

    def clear_quality(self, tag: str) -> None:
        with self._lock:
            self._qualities.pop(tag, None)

    def clear_all(self) -> None:
        with self._lock:
            self._qualities.clear()

    def snapshot(self) -> Dict[str, str]:
        """返回当前有效质量码覆盖的副本。"""
        with self._lock:
            return dict(self._qualities)