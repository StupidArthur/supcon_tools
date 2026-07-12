from __future__ import annotations

from ua_test_harness.scenario_policy import _SUPPORTED, classify_case


def test_ua1_precise_matrix_contains_thirteen_cases() -> None:
    case_ids = set().union(
        _SUPPORTED.get("UA-1-1", set()),
        _SUPPORTED.get("UA-1-2", set()),
        _SUPPORTED.get("UA-1-5", set()),
    )
    assert len(case_ids) == 13
    assert "UA-1-2-03" not in case_ids
    assert "UA-1-2-05" not in case_ids


def test_shared_ua1_cases_have_deterministic_scenarios() -> None:
    assert classify_case({"id": "UA-1-2-01"}).scenario == "datasource_state"
    assert classify_case({"id": "UA-1-2-08"}).scenario == "datasource_state"
    assert classify_case({"id": "UA-1-2-03"}).executable is False
