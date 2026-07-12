"""生成文档 Case 与 Python catalog 实现状态的机器可读覆盖矩阵。"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CASE_ID_RE = re.compile(r"^UA-\d+-\d+-[A-Za-z0-9][A-Za-z0-9_-]*$")
HEADING_RE = re.compile(r"^#\s+(UA-\d+-\d+)\s*(.*)$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def parse_case_doc(path: Path, repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """解析一个固定六列表格的用例 Markdown。"""
    chapter = path.stem
    chapter_title = chapter
    cases: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        heading = HEADING_RE.match(line.strip())
        if heading:
            chapter = heading.group(1)
            chapter_title = heading.group(2).strip() or chapter
            continue
        cells = _split_table_row(line)
        if not cells or not CASE_ID_RE.fullmatch(cells[0]):
            continue
        if len(cells) != 6:
            malformed.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "line": lineno,
                    "caseId": cells[0],
                    "columnCount": len(cells),
                    "raw": line,
                }
            )
            continue
        case_id, title, precondition, steps, expected, verification = cells
        cases.append(
            {
                "id": case_id,
                "chapter": chapter,
                "chapterTitle": chapter_title,
                "title": title,
                "precondition": precondition,
                "steps": steps,
                "expected": expected,
                "verification": verification,
                "docPath": path.relative_to(repo_root).as_posix(),
                "docLine": lineno,
            }
        )
    return cases, malformed


def _implementation_map() -> dict[str, dict[str, Any]]:
    from ua_test_harness.catalog import all_defs, discover

    discover()
    return {
        item.id: {
            "filePath": item.file_path,
            "lineno": item.lineno,
            "kind": item.kind,
            "timeoutSec": item.timeout_sec,
            "tags": item.tags,
        }
        for item in all_defs()
    }


def build_inventory(
    repo_root: Path,
    *,
    implemented: dict[str, dict[str, Any]] | None = None,
    expected_total: int = 419,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    docs_dir = repo_root / "ua_test_gui" / "doc" / "test_cases"
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"test case docs directory not found: {docs_dir}")

    rows: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for path in sorted(docs_dir.glob("*.md")):
        parsed, bad = parse_case_doc(path, repo_root)
        rows.extend(parsed)
        malformed.extend(bad)

    implementation = implemented if implemented is not None else _implementation_map()
    counts = Counter(row["id"] for row in rows)
    duplicates = sorted(case_id for case_id, count in counts.items() if count > 1)
    documented_ids = set(counts)
    orphan_implementations = sorted(set(implementation) - documented_ids)

    cases: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item["id"]):
        impl = implementation.get(row["id"])
        cases.append(
            {
                **row,
                "implementationStatus": "IMPLEMENTED" if impl else "UNIMPLEMENTED",
                "implementation": impl,
                "verificationStatus": "NOT_VERIFIED",
            }
        )

    implemented_count = sum(1 for row in cases if row["implementationStatus"] == "IMPLEMENTED")
    document_count = len(cases)
    summary = {
        "expectedTotal": expected_total,
        "documented": document_count,
        "implemented": implemented_count,
        "unimplemented": document_count - implemented_count,
        "coveragePercent": round((implemented_count / document_count * 100.0), 2) if document_count else 0.0,
        "duplicateDocumentIds": len(duplicates),
        "malformedRows": len(malformed),
        "orphanImplementations": len(orphan_implementations),
        "structureOk": document_count == expected_total and not duplicates and not malformed,
    }
    return {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "repoRoot": str(repo_root),
        "summary": summary,
        "duplicates": duplicates,
        "malformed": malformed,
        "orphanImplementations": [
            {"id": case_id, "implementation": implementation[case_id]}
            for case_id in orphan_implementations
        ],
        "cases": cases,
    }


def structural_failures(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    failures: list[str] = []
    if summary["documented"] != summary["expectedTotal"]:
        failures.append(
            f"documented case count {summary['documented']} != expected {summary['expectedTotal']}"
        )
    if summary["duplicateDocumentIds"]:
        failures.append(f"duplicate document ids: {summary['duplicateDocumentIds']}")
    if summary["malformedRows"]:
        failures.append(f"malformed rows: {summary['malformedRows']}")
    return failures


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.case_inventory")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-total", type=int, default=419)
    parser.add_argument("--strict-structure", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = build_inventory(
        Path(args.repo_root),
        expected_total=args.expected_total,
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(
        "case inventory written: "
        f"{output} documented={summary['documented']} "
        f"implemented={summary['implemented']} "
        f"unimplemented={summary['unimplemented']} "
        f"coverage={summary['coveragePercent']}%"
    )
    failures = structural_failures(report)
    if args.strict_structure and failures:
        for failure in failures:
            print(f"STRUCTURE_ERROR: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())