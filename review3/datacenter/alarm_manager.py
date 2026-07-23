"""
运行报警管理器（AlarmManager）

每条报警的状态机：
    normal → pending → active_unacked → active_acked
                     ↘ returned_unacked ↗
语义（高报警）：
    value >= limit            → pending
    持续 delay_seconds        → active_unacked
    value < limit - deadband  → returned_unacked（曾激活）或 normal
低报警方向相反。
确认规则：
    active_unacked 确认 → active_acked
    active_acked 条件恢复 → normal
    active_unacked 未确认但恢复 → returned_unacked
    returned_unacked 确认 → normal

报警使用真实运行 snapshot，不使用 UA 强制输出。
计时使用 monotonic clock；事件时间同时记录 wall-clock ISO。
报警计算异常不得阻塞 Engine 周期（由调用方 try/except 包裹）。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

STATE_NORMAL = "normal"
STATE_PENDING = "pending"
STATE_ACTIVE_UNACKED = "active_unacked"
STATE_ACTIVE_ACKED = "active_acked"
STATE_RETURNED_UNACKED = "returned_unacked"

MAX_EVENTS = 5000


@dataclass
class AlarmRuleSpec:
    id: str
    name: str
    tag: str
    direction: str  # high | low
    limit: float
    severity: str
    delay_seconds: float
    deadband: float
    enabled: bool
    message: str = ""


@dataclass
class AlarmStatus:
    id: str
    name: str
    tag: str
    severity: str
    state: str
    value: Optional[float]
    limit: float
    direction: str
    message: str
    activated_at: Optional[str] = None
    acknowledged_at: Optional[str] = None


@dataclass
class _AlarmRuntime:
    rule: AlarmRuleSpec
    state: str = STATE_NORMAL
    pending_since: Optional[float] = None  # monotonic
    activated_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    last_value: Optional[float] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class AlarmManager:
    def __init__(self, rules: List[AlarmRuleSpec]):
        self._lock = threading.Lock()
        self._alarms: Dict[str, _AlarmRuntime] = {
            r.id: _AlarmRuntime(rule=r) for r in rules
        }
        self._events: Deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)

    def _in_alarm_condition(self, rt: _AlarmRuntime, value: float) -> bool:
        r = rt.rule
        if r.direction == "high":
            return value >= r.limit
        return value <= r.limit

    def _recovered(self, rt: _AlarmRuntime, value: float) -> bool:
        r = rt.rule
        if r.direction == "high":
            return value < r.limit - r.deadband
        return value > r.limit + r.deadband

    def _record_event(self, rt: _AlarmRuntime, event_type: str, value: Optional[float]) -> None:
        self._events.append({
            "id": rt.rule.id,
            "name": rt.rule.name,
            "tag": rt.rule.tag,
            "severity": rt.rule.severity,
            "type": event_type,
            "value": value,
            "time": _now_iso(),
        })

    def evaluate(self, snapshot: Dict[str, Any]) -> None:
        """基于真实 snapshot 评估全部报警。单条异常不影响其它报警。"""
        now = time.monotonic()
        with self._lock:
            for rt in self._alarms.values():
                try:
                    self._evaluate_one(rt, snapshot, now)
                except Exception:
                    # 单条报警异常不阻塞整体
                    continue

    def _evaluate_one(self, rt: _AlarmRuntime, snapshot: Dict[str, Any], now: float) -> None:
        if not rt.rule.enabled:
            return
        raw = snapshot.get(rt.rule.tag)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            return
        rt.last_value = value

        in_cond = self._in_alarm_condition(rt, value)
        recovered = self._recovered(rt, value)

        if rt.state == STATE_NORMAL:
            if in_cond:
                if rt.rule.delay_seconds <= 0:
                    rt.state = STATE_ACTIVE_UNACKED
                    rt.activated_at = _now_iso()
                    self._record_event(rt, "activated", value)
                else:
                    rt.state = STATE_PENDING
                    rt.pending_since = now
        elif rt.state == STATE_PENDING:
            if recovered:
                rt.state = STATE_NORMAL
                rt.pending_since = None
            elif in_cond and (now - (rt.pending_since or now)) >= rt.rule.delay_seconds:
                rt.state = STATE_ACTIVE_UNACKED
                rt.activated_at = _now_iso()
                rt.pending_since = None
                self._record_event(rt, "activated", value)
        elif rt.state == STATE_ACTIVE_UNACKED:
            if recovered:
                rt.state = STATE_RETURNED_UNACKED
                self._record_event(rt, "returned", value)
        elif rt.state == STATE_ACTIVE_ACKED:
            if recovered:
                rt.state = STATE_NORMAL
                rt.activated_at = None
                rt.acknowledged_at = None
                self._record_event(rt, "normal", value)
        elif rt.state == STATE_RETURNED_UNACKED:
            if in_cond:
                rt.state = STATE_ACTIVE_UNACKED
                rt.activated_at = _now_iso()
                self._record_event(rt, "activated", value)

    def acknowledge(self, alarm_id: str) -> bool:
        with self._lock:
            rt = self._alarms.get(alarm_id)
            if rt is None:
                return False
            if rt.state == STATE_ACTIVE_UNACKED:
                rt.state = STATE_ACTIVE_ACKED
                rt.acknowledged_at = _now_iso()
                self._record_event(rt, "acknowledged", rt.last_value)
                return True
            if rt.state == STATE_RETURNED_UNACKED:
                rt.state = STATE_NORMAL
                rt.acknowledged_at = _now_iso()
                rt.activated_at = None
                self._record_event(rt, "normal", rt.last_value)
                return True
            return False

    def acknowledge_all(self) -> int:
        with self._lock:
            ids = [aid for aid, rt in self._alarms.items()
                   if rt.state in (STATE_ACTIVE_UNACKED, STATE_RETURNED_UNACKED)]
        count = 0
        for aid in ids:
            if self.acknowledge(aid):
                count += 1
        return count

    def statuses(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = []
            for rt in self._alarms.values():
                out.append({
                    "id": rt.rule.id,
                    "name": rt.rule.name,
                    "tag": rt.rule.tag,
                    "severity": rt.rule.severity,
                    "direction": rt.rule.direction,
                    "state": rt.state,
                    "value": rt.last_value,
                    "limit": rt.rule.limit,
                    "activatedAt": rt.activated_at,
                    "acknowledgedAt": rt.acknowledged_at,
                    "message": rt.rule.message,
                })
            return out

    def events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            evs = list(self._events)
        if limit is not None and limit > 0:
            return evs[-limit:]
        return evs
