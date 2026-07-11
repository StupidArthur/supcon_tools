"""YAML 解析器 + 报告渲染单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ua_tpt_loop import (
    LoopResult,
    MockerSpec,
    StepResult,
    format_loop_report,
    format_step_line,
)
from ua_tpt_loop.mocker_yaml import MOCKER_TYPE_TO_TPT
from ua_tpt_loop.ua_client import connect_endpoint


SAMPLE_YAML = """
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1

nodes:
  - name: "tag_"
    type: Double
    count: 3
    change: true
    writable: false
  - name: "str_var"
    type: String
    count: 2
    change: false
    writable: true
    default: "hi"
  - name: "bo_"
    type: Boolean
    count: 2
    writable: false
    change: true
"""


def test_from_yaml_basic(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")
    spec = MockerSpec.from_yaml(p)

    assert spec.host == "0.0.0.0"
    assert spec.port == 18950
    assert spec.cycle_ms == 1000
    assert spec.namespace_index == 1
    assert spec.endpoint == "opc.tcp://0.0.0.0:18950/ua_mocker/"

    # tag_ + count=3 → tag_1, tag_2, tag_3
    tag_node = spec.nodes[0]
    assert tag_node.type == "Double"
    assert tag_node.count == 3
    assert tag_node.change is True
    assert tag_node.expected_node_ids == ["tag_1", "tag_2", "tag_3"]
    assert tag_node.tpt_data_type == 11  # DOUBLE

    # String → tpt 不支持
    str_node = spec.nodes[1]
    assert str_node.tpt_data_type is None
    assert str_node.expected_node_ids == ["str_var1", "str_var2"]

    # Boolean → tpt_data_type=1
    bo_node = spec.nodes[2]
    assert bo_node.tpt_data_type == 1
    assert bo_node.expected_node_ids == ["bo_1", "bo_2"]


def test_all_expected_node_ids_order(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")
    spec = MockerSpec.from_yaml(p)
    assert spec.all_expected_node_ids == [
        "tag_1", "tag_2", "tag_3",
        "str_var1", "str_var2",
        "bo_1", "bo_2",
    ]


def test_registerable_vs_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")
    spec = MockerSpec.from_yaml(p)

    registerable = spec.registerable_node_ids
    # 3 tag_ + 2 bo_ = 5 registerable
    assert len(registerable) == 5
    assert all(dt in (1, 11) for _, dt in registerable)

    unsupported = spec.unsupported_node_ids
    assert unsupported == ["str_var1", "str_var2"]


def test_yaml_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        MockerSpec.from_yaml("/nonexistent/path.yaml")


def test_mocker_type_to_tpt_covers_common() -> None:
    """覆盖常见的 11 种数值/布尔类型。"""
    for k in ["Boolean", "SByte", "Byte", "Short", "UShort", "Int32", "UInt32",
              "Int64", "UInt64", "Float", "Double"]:
        assert MOCKER_TYPE_TO_TPT[k] is not None
    assert MOCKER_TYPE_TO_TPT["String"] is None
    assert MOCKER_TYPE_TO_TPT["DateTime"] is None


def test_connect_endpoint_translates_wildcard() -> None:
    """0.0.0.0 / :: 应被翻译成 127.0.0.1，真实 IP 不变。"""
    assert connect_endpoint("opc.tcp://0.0.0.0:18950/ua_mocker/") == \
        "opc.tcp://127.0.0.1:18950/ua_mocker/"
    assert connect_endpoint("opc.tcp://[::]:18950/ua_mocker/") == \
        "opc.tcp://127.0.0.1:18950/ua_mocker/"
    assert connect_endpoint("opc.tcp://10.10.58.105:18950/ua_mocker/") == \
        "opc.tcp://10.10.58.105:18950/ua_mocker/"
    # 无 host 的兜底
    assert connect_endpoint("opc.tcp://example.com:18950/x/") == \
        "opc.tcp://example.com:18950/x/"


def test_report_format_step_line_pass() -> None:
    step = StepResult(
        index=1, name="ua-server node", passed=True,
        summary="endpoint, 5 nodes",
        details={"sample_values": {"tag_1": 1.0}},
    )
    line = format_step_line(step)
    assert "[1/4]" in line
    assert "PASS" in line
    assert "ua-server node" in line


def test_report_format_step_line_fail() -> None:
    step = StepResult(
        index=2, name="tpt data source", passed=False,
        summary="", error="connection refused",
    )
    line = format_step_line(step)
    assert "FAIL" in line
    assert "connection refused" in line


def test_report_format_loop_report() -> None:
    result = LoopResult(
        steps=[
            StepResult(1, "ua-server node", True, "5 nodes"),
            StepResult(2, "tpt data source", True, "ds_id=5"),
            StepResult(3, "tpt tags", True, "5/5"),
            StepResult(4, "tpt data flow", False, "", error="timeout"),
        ],
        mocker_endpoint="opc.tcp://localhost:18950/ua_mocker/",
        tpt_url="http://10.10.58.153:31501",
    )
    report = format_loop_report(result)
    assert "PASS" in report
    assert "FAIL" in report
    assert "Loop is broken." in report
    assert "3/4 steps passed" in report
    assert not result.is_closed


def test_report_loop_closed() -> None:
    result = LoopResult(
        steps=[StepResult(i + 1, f"step {i + 1}", True, "ok") for i in range(4)],
        mocker_endpoint="opc.tcp://x", tpt_url="http://x",
    )
    assert result.is_closed
    assert result.summary().endswith("Loop is closed.")
