"""verification overlay merge 单测。"""
from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_inventory import (
    build_inventory,
    verification_overlay_from_run,
)


def test_verification_overlay_from_run_maps_pass_and_fail(tmp_path: Path) -> None:
    overlay = verification_overlay_from_run(
        [
            {"caseId": "UA-2-1-017", "status": "PASS", "reportPath": "/a/report.json"},
            {"caseId": "UA-2-1-019", "status": "FAIL", "reportPath": "/b/report.json"},
            {"caseId": "UA-2-1-099", "status": "TIMEOUT"},
        ]
    )
    assert overlay["UA-2-1-017"]["status"] == "VERIFIED"
    assert overlay["UA-2-1-019"]["status"] == "VERIFIED_FAIL"
    assert overlay["UA-2-1-099"]["status"] == "VERIFIED_BLOCKED"


def test_build_inventory_merges_verification_overlay(tmp_path: Path) -> None:
    doc = tmp_path / "ua_test_gui" / "doc" / "test_cases" / "UA-1-1.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        """# UA-1-1 连接建立
| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |
|---|---|---|---|---|---|
| UA-1-1-01 | A | P | S | E | V |
""",
        encoding="utf-8",
    )
    report = build_inventory(
        tmp_path,
        implemented={"UA-1-1-01": {"filePath": "t.py", "lineno": 1}},
        expected_total=1,
        verification_overlay={"UA-1-1-01": {"status": "VERIFIED", "verifiedAt": "t0"}},
    )
    assert report["cases"][0]["verificationStatus"] == "VERIFIED"
    assert report["summary"]["verified"] == 1
