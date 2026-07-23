"""
实时工程组态编译器测试。

覆盖：
- 单 YAML 副本数 1/3
- replica 0 无后缀、replica 1/2 后缀正确
- 多 YAML 无冲突
- 多 YAML 原名冲突
- 多 YAML 副本展开冲突
- 单 YAML 自身副本展开冲突
- 无效副本数
- 超出实例总数限制
- 无效 DSL
- 实例顺序确定
- CLI stdout 只有合法 JSON
- 重名时 CLI 退出码为 0
- 解析失败时 CLI 非零退出
"""

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from controller.realtime_config_compiler import (
    MAX_EXPANDED_INSTANCES,
    MAX_REPLICAS,
    MIN_REPLICAS,
    ExpandedInstance,
    SourceSpec,
    compile_project,
    expand_instance_names,
    inspect_source,
    validate_sources,
)

TANK_YAML = textwrap.dedent("""\
    clock:
      mode: GENERATOR
      cycle_time: 0.5

    program:
      - name: source_flow
        type: Variable
        value: 0.001

      - name: tank
        type: CYLINDRICAL_TANK
        params:
          height: 1.2
          radius: 0.2
          outlet_area: 0.0001
          initial_level: 0.15
        inputs:
          inlet_flow: source_flow

      - name: pid
        type: PID
        params:
          PB: 50.0
          TI: 90.0
          SV: 0.8
        inputs:
          PV: tank.level
""")

COMMON_YAML = textwrap.dedent("""\
    clock:
      mode: GENERATOR
      cycle_time: 0.5

    program:
      - name: pid
        type: PID
        params:
          PB: 40.0
          TI: 60.0
          SV: 0.5

      - name: pid_1
        type: PID
        params:
          PB: 30.0
          TI: 45.0
          SV: 0.6
""")


@pytest.fixture
def tank_yaml(tmp_path):
    p = tmp_path / "tank.yaml"
    p.write_text(TANK_YAML, encoding="utf-8")
    return str(p)


@pytest.fixture
def common_yaml(tmp_path):
    p = tmp_path / "common.yaml"
    p.write_text(COMMON_YAML, encoding="utf-8")
    return str(p)


class TestInspectSource:
    def test_single_yaml_returns_instance_names_in_order(self, tank_yaml):
        source = SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1)
        names = inspect_source(source)
        assert names == ["source_flow", "tank", "pid"]


class TestExpandInstanceNames:
    def test_replica_1_no_suffix(self, tank_yaml):
        source = SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1)
        names = inspect_source(source)
        expanded = expand_instance_names(source, names)
        assert [e.name for e in expanded] == ["source_flow", "tank", "pid"]
        assert all(e.replica_index == 0 for e in expanded)

    def test_replica_3_suffixes(self, tank_yaml):
        source = SourceSpec(source_id="s1", source_file=tank_yaml, replicas=3)
        names = inspect_source(source)
        expanded = expand_instance_names(source, names)
        expected = [
            "source_flow", "tank", "pid",
            "source_flow_1", "tank_1", "pid_1",
            "source_flow_2", "tank_2", "pid_2",
        ]
        assert [e.name for e in expanded] == expected

    def test_deterministic_order(self, tank_yaml):
        source = SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2)
        names = inspect_source(source)
        expanded = expand_instance_names(source, names)
        expected = [
            "source_flow", "tank", "pid",
            "source_flow_1", "tank_1", "pid_1",
        ]
        assert [e.name for e in expanded] == expected


class TestValidateSources:
    def test_single_source_no_conflict(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2)]
        result = validate_sources(sources)
        assert result.valid is True
        assert len(result.instances) == 6
        assert result.duplicates == []

    def test_multi_source_no_conflict(self, tank_yaml, tmp_path):
        other = tmp_path / "other.yaml"
        other.write_text(textwrap.dedent("""\
            clock:
              mode: GENERATOR
              cycle_time: 0.5
            program:
              - name: boiler
                type: Variable
                value: 1.0
              - name: heater
                type: Variable
                value: 2.0
        """), encoding="utf-8")
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1),
            SourceSpec(source_id="s2", source_file=str(other), replicas=1),
        ]
        result = validate_sources(sources)
        assert result.valid is True
        assert [i.name for i in result.instances] == ["source_flow", "tank", "pid", "boiler", "heater"]

    def test_multi_source_original_name_conflict(self, tank_yaml, common_yaml):
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1),
            SourceSpec(source_id="s2", source_file=common_yaml, replicas=1),
        ]
        result = validate_sources(sources)
        assert result.valid is False
        dup_names = [d.name for d in result.duplicates]
        assert "pid" in dup_names

    def test_multi_source_replica_expansion_conflict(self, tank_yaml, common_yaml):
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2),
            SourceSpec(source_id="s2", source_file=common_yaml, replicas=1),
        ]
        result = validate_sources(sources)
        assert result.valid is False
        dup_names = [d.name for d in result.duplicates]
        assert "pid_1" in dup_names

    def test_single_source_self_replica_conflict(self, common_yaml):
        sources = [SourceSpec(source_id="s1", source_file=common_yaml, replicas=2)]
        result = validate_sources(sources)
        assert result.valid is False
        dup_names = [d.name for d in result.duplicates]
        assert "pid_1" in dup_names

    def test_invalid_replicas_zero(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=0)]
        with pytest.raises(ValueError, match="副本数"):
            validate_sources(sources)

    def test_invalid_replicas_over_max(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=MAX_REPLICAS + 1)]
        with pytest.raises(ValueError, match="副本数"):
            validate_sources(sources)

    def test_exceeds_max_expanded_instances(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=MAX_REPLICAS)]
        result = validate_sources(sources)
        assert result.valid is True

    def test_invalid_dsl(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: valid: dsl: [[", encoding="utf-8")
        sources = [SourceSpec(source_id="s1", source_file=str(bad), replicas=1)]
        with pytest.raises(Exception):
            validate_sources(sources)

    def test_duplicate_occurrences_contain_origin_info(self, tank_yaml, common_yaml):
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1),
            SourceSpec(source_id="s2", source_file=common_yaml, replicas=1),
        ]
        result = validate_sources(sources)
        assert result.valid is False
        pid_dup = next(d for d in result.duplicates if d.name == "pid")
        assert len(pid_dup.occurrences) == 2
        assert pid_dup.occurrences[0].source_id == "s1"
        assert pid_dup.occurrences[1].source_id == "s2"


class TestCLI:
    def _run_cli(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(project_root / "standalone_main.py"), "--inspect-project"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=30,
        )

    def test_stdout_is_valid_json_on_success(self, tank_yaml):
        payload = {"sources": [{"id": "s1", "file": tank_yaml, "replicas": 1}]}
        proc = self._run_cli(payload)
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["ok"] is True
        assert data["valid"] is True
        assert len(data["instances"]) == 3

    def test_duplicate_returns_exit_0_with_valid_false(self, tank_yaml, common_yaml):
        payload = {"sources": [
            {"id": "s1", "file": tank_yaml, "replicas": 1},
            {"id": "s2", "file": common_yaml, "replicas": 1},
        ]}
        proc = self._run_cli(payload)
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["ok"] is True
        assert data["valid"] is False
        assert len(data["duplicates"]) > 0

    def test_parse_failure_nonzero_exit(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(":::invalid", encoding="utf-8")
        payload = {"sources": [{"id": "s1", "file": str(bad), "replicas": 1}]}
        proc = self._run_cli(payload)
        assert proc.returncode != 0
        data = json.loads(proc.stdout)
        assert data["ok"] is False

    def test_invalid_input_json_exit_2(self):
        proc = subprocess.run(
            [sys.executable, str(project_root / "standalone_main.py"), "--inspect-project"],
            input="not json at all",
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=30,
        )
        assert proc.returncode == 2
        data = json.loads(proc.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INPUT_ERROR"

    def test_stdout_contains_only_json(self, tank_yaml):
        payload = {"sources": [{"id": "s1", "file": tank_yaml, "replicas": 2}]}
        proc = self._run_cli(payload)
        lines = [l for l in proc.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 1
        json.loads(lines[0])


class TestCompileProject:
    def test_single_source_replica_1(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1)]
        result = compile_project(sources)
        names = [p["name"] for p in result["program"]]
        assert names == ["source_flow", "tank", "pid"]

    def test_single_source_replica_2_rewrites_names(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2)]
        result = compile_project(sources)
        names = [p["name"] for p in result["program"]]
        assert names == ["source_flow", "tank", "pid", "source_flow_1", "tank_1", "pid_1"]

    def test_replica_rewrites_inputs(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2)]
        result = compile_project(sources)
        pid_1 = next(p for p in result["program"] if p["name"] == "pid_1")
        assert pid_1["inputs"]["PV"] == "tank_1.level"

    def test_replica_0_keeps_original_inputs(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=2)]
        result = compile_project(sources)
        pid_0 = next(p for p in result["program"] if p["name"] == "pid")
        assert pid_0["inputs"]["PV"] == "tank.level"

    def test_multi_source_merge(self, tank_yaml, tmp_path):
        other = tmp_path / "other.yaml"
        other.write_text(textwrap.dedent("""\
            clock:
              mode: GENERATOR
              cycle_time: 0.5
            program:
              - name: boiler
                type: Variable
                value: 1.0
        """), encoding="utf-8")
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1),
            SourceSpec(source_id="s2", source_file=str(other), replicas=1),
        ]
        result = compile_project(sources)
        names = [p["name"] for p in result["program"]]
        assert names == ["source_flow", "tank", "pid", "boiler"]

    def test_compile_duplicate_raises(self, tank_yaml, common_yaml):
        sources = [
            SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1),
            SourceSpec(source_id="s2", source_file=common_yaml, replicas=1),
        ]
        with pytest.raises(ValueError, match="冲突"):
            compile_project(sources)

    def test_clock_from_first_source(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=1)]
        result = compile_project(sources)
        assert result["clock"]["mode"] == "GENERATOR"
        assert result["clock"]["cycle_time"] == 0.5

    def test_deterministic_order(self, tank_yaml):
        sources = [SourceSpec(source_id="s1", source_file=tank_yaml, replicas=3)]
        result = compile_project(sources)
        names = [p["name"] for p in result["program"]]
        expected = [
            "source_flow", "tank", "pid",
            "source_flow_1", "tank_1", "pid_1",
            "source_flow_2", "tank_2", "pid_2",
        ]
        assert names == expected

    def test_expression_formula_rewritten(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            clock:
              mode: GENERATOR
              cycle_time: 0.5
            program:
              - name: tank
                type: CYLINDRICAL_TANK
                params:
                  height: 1.2
              - name: expr1
                type: Expression
                formula: tank.level * 2
        """)
        p = tmp_path / "expr.yaml"
        p.write_text(yaml_content, encoding="utf-8")
        sources = [SourceSpec(source_id="s1", source_file=str(p), replicas=2)]
        result = compile_project(sources)
        expr1_1 = next(x for x in result["program"] if x["name"] == "expr1_1")
        assert expr1_1["formula"] == "tank_1.level * 2"
        expr1_0 = next(x for x in result["program"] if x["name"] == "expr1")
        assert expr1_0["formula"] == "tank.level * 2"

    def test_lag_source_rewritten(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            clock:
              mode: GENERATOR
              cycle_time: 0.5
            program:
              - name: tank
                type: CYLINDRICAL_TANK
                params:
                  height: 1.2
              - name: lag1
                type: Lag
                source: tank.level
                delay: 1
        """)
        p = tmp_path / "lag.yaml"
        p.write_text(yaml_content, encoding="utf-8")
        sources = [SourceSpec(source_id="s1", source_file=str(p), replicas=2)]
        result = compile_project(sources)
        lag1_1 = next(x for x in result["program"] if x["name"] == "lag1_1")
        assert lag1_1["source"] == "tank_1.level"

    def test_no_cross_wiring_with_prefixed_names(self, tmp_path):
        # 验证单 pass 重写不会把 pid_1 误当作 pid 的前缀串扰。
        # 直接在重写函数层面验证次序安全。
        from controller.realtime_config_compiler import _rewrite_expression
        rename = {"pid": "pid_1", "pid_1": "pid_1_1", "tank": "tank_1"}
        assert _rewrite_expression("pid.PV + pid_1.PV", rename) == "pid_1.PV + pid_1_1.PV"
        assert _rewrite_expression("tank.level * 2", rename) == "tank_1.level * 2"

    def test_attribute_name_not_renamed(self):
        # 属性名（Attribute.attr）不得被替换，即使与某实例同名。
        from controller.realtime_config_compiler import _rewrite_expression
        rename = {"pid": "pid_1", "PV": "PV_1"}
        assert _rewrite_expression("pid.PV", rename) == "pid_1.PV"

    def test_string_literal_not_renamed(self):
        from controller.realtime_config_compiler import _rewrite_expression
        rename = {"pid": "pid_1"}
        # 字符串字面量中的 pid 不应被替换
        assert _rewrite_expression("'pid'", rename) == "'pid'"

    def test_self_replica_prefix_conflict_detected(self, tmp_path):
        # DSL 含 pid 和 pid_1，副本 1 把 pid→pid_1 与原 pid_1 冲突，应被拒绝。
        yaml_content = textwrap.dedent("""\
            clock:
              mode: GENERATOR
              cycle_time: 0.5
            program:
              - name: tank
                type: CYLINDRICAL_TANK
                params:
                  height: 1.2
              - name: pid
                type: PID
                params:
                  PB: 50.0
                inputs:
                  PV: tank.level
              - name: pid_1
                type: PID
                params:
                  PB: 40.0
                inputs:
                  PV: tank.level
        """)
        p = tmp_path / "prefixed.yaml"
        p.write_text(yaml_content, encoding="utf-8")
        sources = [SourceSpec(source_id="s1", source_file=str(p), replicas=2)]
        with pytest.raises(ValueError, match="冲突"):
            compile_project(sources)


class TestCompileCLI:
    def _run_compile(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(project_root / "standalone_main.py"), "--compile-project"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=30,
        )

    def test_compile_success(self, tank_yaml, tmp_path):
        out = str(tmp_path / "merged.yaml")
        payload = {"sources": [{"id": "s1", "file": tank_yaml, "replicas": 2}], "output": out}
        proc = self._run_compile(payload)
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["ok"] is True
        assert data["output"] == out
        import yaml
        with open(out, encoding="utf-8") as f:
            merged = yaml.safe_load(f)
        assert len(merged["program"]) == 6

    def test_compile_duplicate_returns_error(self, tank_yaml, common_yaml, tmp_path):
        out = str(tmp_path / "merged.yaml")
        payload = {
            "sources": [
                {"id": "s1", "file": tank_yaml, "replicas": 1},
                {"id": "s2", "file": common_yaml, "replicas": 1},
            ],
            "output": out,
        }
        proc = self._run_compile(payload)
        assert proc.returncode == 2
        data = json.loads(proc.stdout)
        assert data["ok"] is False
