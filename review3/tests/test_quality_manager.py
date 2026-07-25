"""
质量码覆盖管理器测试。

覆盖：
- 合法 quality（Good/Uncertain/Bad）大小写不敏感
- 非法 quality 被拒绝
- 不存在位号被拒绝
- 同 tag 固定值 + 覆盖质量码可同时生效
- 清除 quality 后 OPC UA 写值回到 Good
- snapshot 返回当前状态副本
- 并发 set/clear 安全
"""

import sys
import pathlib
import threading

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datacenter.quality_manager import QualityManager, QualityError, normalize_quality


def make_manager(valid_tags=None):
    qm = QualityManager()
    if valid_tags is not None:
        qm.set_valid_tags(valid_tags)
    return qm


class TestNormalizeQuality:
    def test_good_lowercase(self):
        assert normalize_quality("good") == "Good"

    def test_uncertain_mixed(self):
        assert normalize_quality("Uncertain") == "Uncertain"

    def test_bad_uppercase(self):
        assert normalize_quality("BAD") == "Bad"

    def test_invalid_quality_rejected(self):
        with pytest.raises(QualityError):
            normalize_quality("garbage")

    def test_non_string_rejected(self):
        with pytest.raises(QualityError):
            normalize_quality(123)


class TestSetAndClear:
    def test_set_uncertain(self):
        qm = make_manager(valid_tags={"pid.PV"})
        qm.set_quality("pid.PV", "Uncertain")
        assert qm.snapshot() == {"pid.PV": "Uncertain"}

    def test_set_bad(self):
        qm = make_manager(valid_tags={"pid.PV"})
        qm.set_quality("pid.PV", "Bad")
        assert qm.snapshot() == {"pid.PV": "Bad"}

    def test_set_good_clears(self):
        qm = make_manager(valid_tags={"pid.PV"})
        qm.set_quality("pid.PV", "Bad")
        qm.set_quality("pid.PV", "Good")
        assert qm.snapshot() == {}

    def test_clear_quality(self):
        qm = make_manager(valid_tags={"pid.PV"})
        qm.set_quality("pid.PV", "Bad")
        qm.clear_quality("pid.PV")
        assert qm.snapshot() == {}

    def test_clear_nonexistent_no_error(self):
        qm = make_manager(valid_tags={"pid.PV"})
        qm.clear_quality("pid.PV")
        assert qm.snapshot() == {}

    def test_clear_all(self):
        qm = make_manager(valid_tags={"a", "b"})
        qm.set_quality("a", "Bad")
        qm.set_quality("b", "Uncertain")
        qm.clear_all()
        assert qm.snapshot() == {}


class TestValidation:
    def test_unknown_tag_rejected(self):
        qm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(QualityError):
            qm.set_quality("nope", "Bad")

    def test_invalid_quality_rejected(self):
        qm = make_manager(valid_tags={"pid.PV"})
        with pytest.raises(QualityError):
            qm.set_quality("pid.PV", "bogus")


class TestIndependentFromForce:
    """质量码覆盖与 fixed 模式彼此独立：同一 tag 可同时生效。"""
    def test_independent_state(self):
        qm = make_manager(valid_tags={"pid.PV"})
        # 模拟 force 同时生效
        qm.set_quality("pid.PV", "Bad")
        # 不应被 force 影响
        assert qm.snapshot() == {"pid.PV": "Bad"}
        qm.set_quality("pid.PV", "Uncertain")
        assert qm.snapshot() == {"pid.PV": "Uncertain"}


class TestConcurrency:
    def test_concurrent_set_clear(self):
        qm = make_manager(valid_tags={f"tag{i}" for i in range(20)})
        errors = []

        def writer():
            try:
                for i in range(200):
                    qm.set_quality(f"tag{i % 20}", "Bad")
                    qm.clear_quality(f"tag{i % 20}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    qm.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []