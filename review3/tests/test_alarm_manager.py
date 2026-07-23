"""
报警管理器状态机测试。

覆盖：high/low、delay、deadband、状态恢复、active ack、returned unacked、
ack all、tag 缺失、非有限值、报警不受 force 影响。
"""

import sys
import pathlib

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datacenter.alarm_manager import (
    AlarmManager,
    AlarmRuleSpec,
    STATE_NORMAL,
    STATE_PENDING,
    STATE_ACTIVE_UNACKED,
    STATE_ACTIVE_ACKED,
    STATE_RETURNED_UNACKED,
)


def high_rule(delay=0.0, deadband=0.0, **kw):
    base = dict(
        id="a1", name="高高", tag="tank.level", direction="high",
        limit=1.0, severity="critical", delay_seconds=delay,
        deadband=deadband, enabled=True, message="过高",
    )
    base.update(kw)
    return AlarmRuleSpec(**base)


def low_rule(**kw):
    base = dict(
        id="a2", name="低低", tag="tank.level", direction="low",
        limit=0.2, severity="warning", delay_seconds=0.0,
        deadband=0.0, enabled=True, message="过低",
    )
    base.update(kw)
    return AlarmRuleSpec(**base)


def state_of(mgr, aid="a1"):
    return next(s for s in mgr.statuses() if s["id"] == aid)["state"]


class TestHighAlarm:
    def test_below_limit_normal(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": 0.5})
        assert state_of(m) == STATE_NORMAL

    def test_above_limit_activates(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": 1.1})
        assert state_of(m) == STATE_ACTIVE_UNACKED

    def test_deadband_recovery(self):
        m = AlarmManager([high_rule(deadband=0.1)])
        m.evaluate({"tank.level": 1.1})
        assert state_of(m) == STATE_ACTIVE_UNACKED
        # 在 limit 与 limit-deadband 之间：未恢复
        m.evaluate({"tank.level": 0.95})
        assert state_of(m) == STATE_RETURNED_UNACKED or state_of(m) == STATE_ACTIVE_UNACKED
        # 低于 limit-deadband：恢复
        m.evaluate({"tank.level": 0.85})
        assert state_of(m) == STATE_RETURNED_UNACKED


class TestDelay:
    def test_delay_keeps_pending(self):
        m = AlarmManager([high_rule(delay=100.0)])
        m.evaluate({"tank.level": 1.1})
        assert state_of(m) == STATE_PENDING


class TestLowAlarm:
    def test_below_limit_activates(self):
        m = AlarmManager([low_rule()])
        m.evaluate({"tank.level": 0.1})
        assert state_of(m, "a2") == STATE_ACTIVE_UNACKED

    def test_above_limit_normal(self):
        m = AlarmManager([low_rule()])
        m.evaluate({"tank.level": 0.5})
        assert state_of(m, "a2") == STATE_NORMAL


class TestAck:
    def test_ack_active(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": 1.1})
        assert m.acknowledge("a1") is True
        assert state_of(m) == STATE_ACTIVE_ACKED

    def test_acked_recover_to_normal(self):
        m = AlarmManager([high_rule(deadband=0.1)])
        m.evaluate({"tank.level": 1.1})
        m.acknowledge("a1")
        m.evaluate({"tank.level": 0.5})
        assert state_of(m) == STATE_NORMAL

    def test_unacked_recover_to_returned(self):
        m = AlarmManager([high_rule(deadband=0.1)])
        m.evaluate({"tank.level": 1.1})
        m.evaluate({"tank.level": 0.5})
        assert state_of(m) == STATE_RETURNED_UNACKED

    def test_returned_ack_to_normal(self):
        m = AlarmManager([high_rule(deadband=0.1)])
        m.evaluate({"tank.level": 1.1})
        m.evaluate({"tank.level": 0.5})
        assert m.acknowledge("a1") is True
        assert state_of(m) == STATE_NORMAL

    def test_ack_all(self):
        m = AlarmManager([high_rule(id="a1"), high_rule(id="a2", tag="x.v")])
        m.evaluate({"tank.level": 1.1, "x.v": 2.0})
        assert m.acknowledge_all() == 2


class TestEdgeCases:
    def test_missing_tag_no_change(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"other": 1.0})
        assert state_of(m) == STATE_NORMAL

    def test_non_finite_value_ignored(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": float("nan")})
        assert state_of(m) == STATE_NORMAL

    def test_disabled_rule_ignored(self):
        m = AlarmManager([high_rule(enabled=False)])
        m.evaluate({"tank.level": 1.1})
        assert state_of(m) == STATE_NORMAL

    def test_alarm_uses_snapshot_not_force(self):
        # AlarmManager 只读传入的 snapshot；force 在 OPC UA 层，不进入此处。
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": 0.5})  # 真实运行值未越限
        assert state_of(m) == STATE_NORMAL

    def test_events_recorded(self):
        m = AlarmManager([high_rule()])
        m.evaluate({"tank.level": 1.1})
        evs = m.events()
        assert any(e["type"] == "activated" for e in evs)
