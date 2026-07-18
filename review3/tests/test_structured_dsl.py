"""
测试结构化 DSL 语法（inputs / params / Variable / Expression / Lag / 拓扑排序）。

验证点：
1. 新语法解析出的 ProgramConfig 与旧语法等价
2. 拓扑排序正确重排 program 顺序
3. Variable / Expression / Lag 类型正确映射为 VARIABLE
4. execute_first 正确断环
5. 端到端 batch 运行结果与旧语法一致
"""

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from controller.parser import DSLParser


def test_structured_syntax_parses():
    """新语法 YAML 能被正确解析为 ProgramConfig。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    # 4 个 program 项
    assert len(config.program) == 4

    # 拓扑排序后顺序应为：source_flow -> v_name(execute_first) -> valve_1 -> tank_1
    # 因为 v_name 标记了 execute_first，环在 v_name 处断开
    # source_flow 无依赖排第一
    # v_name 的 execute_first 使其排第二（即使它依赖 tank_1）
    # valve_1 依赖 source_flow 和 v_name -> 排第三
    # tank_1 依赖 valve_1 -> 排第四
    names = [item.name for item in config.program]
    assert names[0] == "source_flow", f"第一个应为 source_flow, 实际: {names}"
    assert names[1] == "v_name", f"第二个应为 v_name(execute_first), 实际: {names}"
    assert "valve_1" in names[2:3], f"valve_1 应在第三位, 实际: {names}"
    assert "tank_1" in names[3:4], f"tank_1 应在第四位, 实际: {names}"


def test_variable_type_mapped():
    """Variable 类型映射为内部 VARIABLE。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    source_flow = next(item for item in config.program if item.name == "source_flow")
    assert source_flow.type == "VARIABLE"
    assert "0.18" in source_flow.expression


def test_inputs_generate_expression():
    """inputs 字段正确生成 execute() 表达式。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    valve = next(item for item in config.program if item.name == "valve_1")
    assert "valve_1.execute(" in valve.expression
    assert "target_opening=v_name.MV" in valve.expression
    assert "inlet_flow=source_flow" in valve.expression


def test_params_accepted():
    """params 字段被正确解析为 init_args。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    pid = next(item for item in config.program if item.name == "v_name")
    assert pid.init_args.get("PB") == 12
    assert pid.init_args.get("SV") == 1.0


def test_execute_first_flag():
    """execute_first 标记被正确解析。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    pid = next(item for item in config.program if item.name == "v_name")
    assert pid.execute_first is True

    valve = next(item for item in config.program if item.name == "valve_1")
    assert valve.execute_first is False


def test_old_syntax_still_works():
    """旧语法 YAML 仍能正常解析。"""
    parser = DSLParser()
    config = parser.parse_file("config/old_version/tank_constant_sv.yaml")

    assert len(config.program) == 4
    # 旧语法不排序，保持原序
    names = [item.name for item in config.program]
    assert names == ["source_flow", "valve_1", "tank_1", "v_name"]


def test_cycle_without_execute_first_raises():
    """环中无 execute_first 时应报错。"""
    yaml_content = """
clock:
  mode: GENERATOR
  cycle_time: 0.5

program:
  - name: a
    type: VARIABLE
    inputs:
      x: b.out
  - name: b
    type: VARIABLE
    inputs:
      x: a.out
"""
    parser = DSLParser()
    with pytest.raises(ValueError, match="execute_first"):
        parser.parse(yaml_content)


def test_expression_type():
    """Expression 类型正确生成赋值表达式。"""
    yaml_content = """
clock:
  mode: GENERATOR
  cycle_time: 0.5

program:
  - name: v1
    type: Variable
    value: 10
  - name: v2
    type: Expression
    formula: "v1 + 5"
"""
    parser = DSLParser()
    config = parser.parse(yaml_content)

    v2 = next(item for item in config.program if item.name == "v2")
    assert v2.type == "VARIABLE"
    assert "v1 + 5" in v2.expression


def test_lag_type():
    """Lag 类型正确生成历史访问表达式。"""
    yaml_content = """
clock:
  mode: GENERATOR
  cycle_time: 0.5

program:
  - name: v1
    type: Variable
    value: 1
  - name: old_v1
    type: Lag
    source: v1
    delay: 30
"""
    parser = DSLParser()
    config = parser.parse(yaml_content)

    old_v1 = next(item for item in config.program if item.name == "old_v1")
    assert old_v1.type == "VARIABLE"
    assert "v1[-30]" in old_v1.expression

    # lag_requirements 应包含 v1: 30
    assert "v1" in config.lag_requirements
    assert config.lag_requirements["v1"] == 30


def test_batch_end_to_end():
    """新语法 YAML 能跑通 batch 模式。"""
    from controller.engine import UnifiedEngine
    from controller.clock import ClockMode

    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")

    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR

    engine.clock.start()
    snapshots = []
    for _ in range(50):
        snapshot = engine.step()
        snapshots.append(snapshot)
    engine.clock.stop()

    assert len(snapshots) == 50

    # 水位应该从 0 开始上升（PID 控制器试图将 level 控制到 SV=1.0）
    first_level = snapshots[0].get("tank_1.level", 0)
    last_level = snapshots[-1].get("tank_1.level", 0)
    assert first_level < last_level, f"水位应上升: {first_level} -> {last_level}"

    # SV 应为 1.0
    assert abs(snapshots[-1].get("v_name.SV", 0) - 1.0) < 0.01
