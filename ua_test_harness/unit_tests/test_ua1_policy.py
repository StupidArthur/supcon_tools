from __future__ import annotations

from ua_test_harness.scenario_policy import _SUPPORTED, classify_case


def test_ua1_precise_matrix_contains_all_chapters() -> None:
    total = sum(len(v) for k, v in _SUPPORTED.items() if k.startswith("UA-1-"))
    assert total == 56, total
    assert "UA-1-2-03" in _SUPPORTED.get("UA-1-2", set())
    assert "UA-1-5-03" in _SUPPORTED.get("UA-1-5", set())


def test_shared_non_ua1_cases_have_deterministic_scenarios() -> None:
    assert classify_case({"id": "UA-3-6-001", "title": "性能"}).scenario == "performance"
    assert classify_case({"id": "UA-3-3-001", "title": "写值"}).scenario == "rt_write"
    assert classify_case({"id": "UA-2-1-001", "title": "新增"}).executable is False
