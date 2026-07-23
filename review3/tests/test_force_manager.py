"""
输出强制管理器测试。

覆盖：
- follow/hold/zero/fixed
- hold 原子捕获当前运行值
- clear 后恢复运行值
- 不存在位号被拒绝
- 非有限 fixed 值被拒绝
- 到期自动恢复 follow
- 并发 set/clear/apply 安全
"""

import sys
import pathlib
import threading

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datacenter.force_manager import ForceManager, ForceError


def make_manager(valid_tags=None, runtime=None):
    fm = ForceManager()
    if runtime is not None:
        fm.bind_runtime(runtime)
    if valid_tags is not None:
        fm.set_valid_tags(valid_tags)
    return fm


class TestForceModes:
    def test_zero_outputs_zero(self):
        fm = make_manager(valid_tags={"pid.PV"})
        fm.set_force("pid.PV", "zero")
        out = fm.apply({"pid.PV": 0.8, "other": 1.0})
        assert out["pid.PV"] == 0.0
        assert out["other"] == 1.0

    def test_fixed_outputs_value(self):
        fm = make_manager(valid_tags={"pid.SV"})
        fm.set_force("pid.SV", "fixed", value=5.0)
        out = fm.apply({"pid.SV": 0.8})
        assert out["pid.SV"] == 5.0

    def test_hold_captures_current_runtime_atomically(self):
        runtime = {"pid.PV": 0.75}
        fm = make_manager(valid_tags={"pid.PV"}, runtime=runtime)
        fm.set_force("pid.PV", "hold")
        runtime["pid.PV"] = 0.99
        out = fm.apply({"pid.PV": 0.99})
        assert out["pid.PV"] == 0.75

    def test_follow_does_not_override(self):
        fm = make_manager(valid_tags={"pid.PV"})
        fm.set_force("pid.PV", "zero")
        fm.set_force("pid.PV", "follow")
        out = fm.apply({"pid.PV": 0.8})
        assert out["pid.PV"] == 0.8

    def test_clear_restores_runtime(self):
        fm = make_manager(valid_tags={"pid.PV"})
        fm.set_force("pid.PV", "zero")
        fm.clear_force("pid.PV")
        out = fm.apply({"pid.PV": 0.8})
        assert out["pid.PV"] == 0.8

    def test_clear_all(self):
        fm = make_manager(valid_tags={"a", "b"})
        fm.set_force("a", "zero")
        fm.set_force("b", "fixed", value=1.0)
        fm.clear_all()
        out = fm.apply({"a": 0.5, "b": 0.5})
        assert out["a"] == 0.5
        assert out["b"] == 0.5


class TestForceValidation:
    def test_invalid_mode_rejected(self):
        fm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(ForceError):
            fm.set_force("pid.PV", "bogus")

    def test_unknown_tag_rejected(self):
        fm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(ForceError):
            fm.set_force("time_str", "zero")

    def test_fixed_requires_value(self):
        fm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(ForceError):
            fm.set_force("pid.PV", "fixed")

    def test_fixed_non_finite_rejected(self):
        fm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(ForceError):
            fm.set_force("pid.PV", "fixed", value=float("inf"))
        with pytest.raises(ForceError):
            fm.set_force("pid.PV", "fixed", value=float("nan"))

    def test_invalid_duration_rejected(self):
        fm = make_manager(valid_tags={"pid.PV"})
        for bad in (0, -5, float("nan"), float("inf")):
            with pytest.raises(ForceError):
                fm.set_force("pid.PV", "zero", duration=bad)

    def test_zero_value_preserved_in_snapshot(self):
        fm = make_manager(valid_tags={"pid.SV"})
        fm.set_force("pid.SV", "fixed", value=0.0)
        snap = fm.snapshot()
        assert snap["pid.SV"]["value"] == 0.0
        out = fm.apply({"pid.SV": 0.8})
        assert out["pid.SV"] == 0.0


class TestForceDuration:
    def test_expired_force_reverts_to_follow(self):
        fm = make_manager(valid_tags={"pid.PV"})
        fm.set_force("pid.PV", "zero", duration=0.01)
        import time
        time.sleep(0.05)
        out = fm.apply({"pid.PV": 0.8})
        assert out["pid.PV"] == 0.8
        assert fm.snapshot() == {}

    def test_active_duration_still_forces(self):
        fm = make_manager(valid_tags={"pid.PV"})
        fm.set_force("pid.PV", "zero", duration=10.0)
        out = fm.apply({"pid.PV": 0.8})
        assert out["pid.PV"] == 0.0


class TestForceConcurrency:
    def test_concurrent_set_clear_apply(self):
        fm = make_manager(valid_tags={f"tag{i}" for i in range(20)})
        errors = []

        def writer():
            try:
                for i in range(200):
                    fm.set_force(f"tag{i % 20}", "zero")
                    fm.clear_force(f"tag{i % 20}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    fm.apply({f"tag{i}": float(i) for i in range(20)})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
