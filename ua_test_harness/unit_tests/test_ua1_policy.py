from __future__ import annotations

from ua_test_harness.scenario_policy import _SUPPORTED, classify_case


def test_ua1_precise_matrix_contains_twelve_cases() -> None:
    case_ids = set().union(
        _SUPPORTED.get("UA-1-1", set()),
        _SUPPORTED.get("UA-1-2", set()),
        _SUPPORTED.get("UA-1-5", set()),
    )
    assert len(case_ids) == 12
    assert "UA-1-2-03" not in case_ids
    assert "UA-1-2-05" not in case_ids
    assert "UA-1-5-03" not in case_ids


def test_shared_non_ua1_cases_have_deterministic_scenarios() -> None:
    assert classify_case({"id": "UA-3-6-001"}).scenario == "performance"
    assert classify_case({"id": "UA-1-2-03"}).executable is False
    assert classify_case({"id": "UA-2-1-001"}).executable is False
    assert classify_case({"id": "UA-2-4-001"}).executable is False
    assert classify_case({"id": "UA-2-5-004"}).executable is False
