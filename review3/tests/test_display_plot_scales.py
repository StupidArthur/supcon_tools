"""
display_args → 趋势图绘图缩放（[ref]）的引擎行为短测试。

验证 DSL display_args 中带 [ref] 的属性会被 get_plot_scales() 输出对应 ref，
不带 [ref] 的属性（default ref=100）也存在；外部调用方据此绘图的 plotValue=raw×100/ref。
引擎层 step() 不缩放原始值，缩放由前端表现层负责。
"""

import math
import pathlib
import sys

project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from controller.parser import DSLParser
from controller.engine import UnifiedEngine

from components import programs  # noqa: F401  触发程序注册
from components import functions  # noqa: F401


def test_plot_scales_refs():
    """display_args 含 [ref] 时 get_display_variables / get_plot_scales 输出。"""
    dsl_yaml = """
clock:
  mode: GENERATOR
  cycle_time: 0.5
program:
  - name: tank
    type: CYLINDRICAL_TANK
    inputs:
      inlet_flow: source_flow
    display_args:
      - "level[1.2]"
  - name: pid
    type: PID
    execute_first: true
    params:
      PB: 100
      TI: 0
      TD: 0
      SV: 0.8
      MODE: 5
    display_args:
      - "MV[100]"
  - name: source_flow
    type: Variable
    value: 0.0012
"""
    parser = DSLParser()
    config = parser.parse(dsl_yaml)
    engine = UnifiedEngine.from_program_config(config)

    display_columns = engine.get_display_variables()
    assert set(display_columns) == {"tank.level", "pid.MV"}

    all_plot_scales = engine.get_plot_scales()
    # ref=1.2 由 [1.2] 给出
    assert all_plot_scales["tank.level"] == 1.2
    # ref=100 由 [100] 给出
    assert all_plot_scales["pid.MV"] == 100.0

    # 模拟 standalone_main 中过滤到 display_columns 的子集：
    plot_scales = {
        col: all_plot_scales[col]
        for col in display_columns
        if col in all_plot_scales
    }
    assert plot_scales == {"tank.level": 1.2, "pid.MV": 100.0}


def test_plot_scales_raw_unchanged():
    """绘图缩放是表现层职责：引擎 step() 输出原始值，未被 display_args 的 ref 缩放。"""
    dsl_yaml = """
clock:
  mode: GENERATOR
  cycle_time: 0.5
program:
  - name: tank
    type: CYLINDRICAL_TANK
    inputs:
      inlet_flow: source_flow
    display_args:
      - "level[1.2]"
  - name: source_flow
    type: Variable
    value: 0.0012
"""
    parser = DSLParser()
    config = parser.parse(dsl_yaml)
    engine = UnifiedEngine.from_program_config(config)
    # 跑较多周期让 tank 进水，确保存在非零、非 ref 的快照可用于断言
    snaps = engine.run_generator(50)
    assert len(snaps) == 50
    assert all("tank.level" in s for s in snaps)
    # 每个原始 level 都是有限浮点数
    assert all(
        isinstance(s["tank.level"], float) and math.isfinite(s["tank.level"])
        for s in snaps
    )
    # 选取至少一个非零原始快照：原始 tank.level 与其按 ref 计算的"缩放值"必须不同，
    # 否则引擎层做了 ref 缩放（违反表现层职责）。
    ref = engine.get_plot_scales()["tank.level"]
    nonzero = [s for s in snaps if abs(s["tank.level"]) > 1e-9]
    assert len(nonzero) > 0, "expected at least one nonzero level snapshot"
    for s in nonzero:
        raw = s["tank.level"]
        scaled = raw * 100 / ref
        assert abs(raw - scaled) > 1e-9, (
            f"engine should output raw tank.level; got raw={raw}, ref*scale={scaled}"
        )
    # get_plot_scales 给出 ref
    assert engine.get_plot_scales()["tank.level"] == 1.2
