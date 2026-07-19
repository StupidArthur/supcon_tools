"""
水箱 DSL 与 PID 闭环组态验收测试。

覆盖：
1. 单水箱 DSL 解析、创建、运行
2. 二阶水箱闭环 DSL 解析、创建、运行
3. 开环二阶水箱辨识组态仍可解析
4. PID 公开参数与量程配置正确
5. 运行过程中 PV/SV/MV 始终为有限值
6. 单水箱响应时间、峰值与最终稳态范围
7. 二阶水箱响应时间、峰值与最终稳态范围
8. 二阶水箱上游液位不触碰高度上限
9. old_version 不进入正常配置发现
10. 原有 DSL/PID 测试无回归（由其他测试文件覆盖，本文件不重复）
"""

import math
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 触发算法/模型注册
import components.programs  # noqa: F401
from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from controller.clock import ClockMode


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------
def _build_engine(yaml_path: str) -> UnifiedEngine:
    """解析 YAML 并构建 GENERATOR 模式引擎。"""
    parser = DSLParser()
    config = parser.parse_file(yaml_path)
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR
    return engine


def _run_cycles(engine: UnifiedEngine, n: int):
    """运行 n 个周期并返回快照列表。"""
    engine.clock.start()
    snapshots = [engine.step() for _ in range(n)]
    engine.clock.stop()
    return snapshots


def _first_cycle_reaching(values, threshold):
    """第一次达到 threshold 的周期索引。"""
    for i, v in enumerate(values):
        if v >= threshold:
            return i
    return None


def _first_cycle_stable_in_band(values, target, pct):
    """
    第一次进入 ±pct% 误差带并持续到末尾的周期索引。

    “稳定周期”定义：第一次进入误差带后，后续周期持续保持在误差带内。
    """
    band = target * pct / 100.0
    n = len(values)
    for i in range(n):
        if all(abs(values[j] - target) <= band for j in range(i, n)):
            return i
    return None


def _peak_cycle(values):
    """返回峰值出现的周期索引。"""
    return max(range(len(values)), key=lambda i: values[i])


def _all_finite(values):
    """所有值是否均为有限数值。"""
    return all(math.isfinite(v) for v in values)


# ----------------------------------------------------------------------
# 1. 单水箱 DSL 解析、创建、运行
# ----------------------------------------------------------------------
def test_single_tank_structured_parses_and_runs():
    """单水箱结构化 DSL 能解析、创建引擎并运行 50 个周期。"""
    engine = _build_engine("config/tank_structured.yaml")
    snapshots = _run_cycles(engine, 50)
    assert len(snapshots) == 50
    # 第一周期后水位应接近初始值 0.15（已有微小变化）
    assert abs(snapshots[0]["tank_1.level"] - 0.15) < 0.01
    assert snapshots[-1]["tank_1.level"] > snapshots[0]["tank_1.level"]


def test_single_tank_classical_parses_and_runs():
    """单水箱经典表达式 DSL（tank_constant_sv.yaml）能解析、创建并运行。"""
    engine = _build_engine("config/tank_constant_sv.yaml")
    snapshots = _run_cycles(engine, 50)
    assert len(snapshots) == 50
    assert snapshots[-1]["tank_1.level"] > snapshots[0]["tank_1.level"]


def test_single_tank_two_syntax_equivalent():
    """结构化与经典表达式两份单水箱 DSL 物理结果等价。"""
    snaps_struct = _run_cycles(_build_engine("config/tank_structured.yaml"), 100)
    snaps_class = _run_cycles(_build_engine("config/tank_constant_sv.yaml"), 100)
    for i in (0, 50, 99):
        assert abs(snaps_struct[i]["tank_1.level"] - snaps_class[i]["tank_1.level"]) < 1e-9, (
            f"周期 {i} 液位不一致: structured={snaps_struct[i]['tank_1.level']}, "
            f"classical={snaps_class[i]['tank_1.level']}"
        )
        assert abs(snaps_struct[i]["pid1.MV"] - snaps_class[i]["pid1.MV"]) < 1e-9


# ----------------------------------------------------------------------
# 2. 二阶水箱闭环 DSL 解析、创建、运行
# ----------------------------------------------------------------------
def test_two_tank_structured_parses_and_runs():
    """二阶水箱闭环结构化 DSL 能解析、创建引擎并运行 50 个周期。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml")
    snapshots = _run_cycles(engine, 50)
    assert len(snapshots) == 50
    # 第一周期后下游水位应接近初始值 0.10（已有微小变化）
    assert abs(snapshots[0]["tank_2.level"] - 0.10) < 0.01
    assert snapshots[-1]["tank_2.level"] > snapshots[0]["tank_2.level"]


def test_two_tank_classical_parses_and_runs():
    """二阶水箱闭环经典表达式 DSL（classical_config）能解析、创建并运行。"""
    engine = _build_engine("classical_config/单阀门二阶水箱.yaml")
    snapshots = _run_cycles(engine, 50)
    assert len(snapshots) == 50
    assert snapshots[-1]["tank_2.level"] > snapshots[0]["tank_2.level"]


def test_two_tank_two_syntax_equivalent():
    """结构化与经典表达式两份二阶水箱 DSL 物理结果等价。"""
    snaps_struct = _run_cycles(_build_engine("config/单阀门二阶水箱.yaml"), 100)
    snaps_class = _run_cycles(_build_engine("classical_config/单阀门二阶水箱.yaml"), 100)
    for i in (0, 50, 99):
        assert abs(snaps_struct[i]["tank_2.level"] - snaps_class[i]["tank_2.level"]) < 1e-9, (
            f"周期 {i} 下游液位不一致: structured={snaps_struct[i]['tank_2.level']}, "
            f"classical={snaps_class[i]['tank_2.level']}"
        )


# ----------------------------------------------------------------------
# 3. 开环二阶水箱辨识组态仍可解析
# ----------------------------------------------------------------------
def test_two_tank_open_loop_configs_parse():
    """开环辨识组态（结构化与经典）仍存在并可解析。"""
    parser = DSLParser()
    # 结构化开环辨识
    config_struct = parser.parse_file("config/单阀门二阶水箱开环辨识.yaml")
    assert len(config_struct.program) > 0
    # 应包含 LIST_WAVE 类型（开环辨识用 mv 驱动阀门）
    types = {item.type for item in config_struct.program}
    assert "LIST_WAVE" in types, f"开环辨识应包含 LIST_WAVE, 实际类型: {types}"

    # 经典开环辨识
    config_class = parser.parse_file("classical_config/单阀门二阶水箱开环辨识.yaml")
    assert len(config_class.program) > 0
    types_class = {item.type for item in config_class.program}
    assert "LIST_WAVE" in types_class


# ----------------------------------------------------------------------
# 4. PID 公开参数与量程配置正确
# ----------------------------------------------------------------------
def test_single_tank_pid_params_correct():
    """单水箱 PID 参数与量程配置正确。"""
    parser = DSLParser()
    config = parser.parse_file("config/tank_structured.yaml")
    pid = next(item for item in config.program if item.name == "pid1")

    assert pid.init_args.get("PB") == 50.0
    assert pid.init_args.get("TI") == 90.0
    assert pid.init_args.get("TD") == 0.0
    assert pid.init_args.get("KD") == 10.0
    assert pid.init_args.get("MODE") == 5
    assert pid.init_args.get("SWPN") == 1
    # 量程
    assert pid.init_args.get("SVSCL") == 0.0
    assert pid.init_args.get("SVSCH") == 1.2
    assert pid.init_args.get("MVSCL") == 0.0
    assert pid.init_args.get("MVSCH") == 100.0
    assert pid.init_args.get("SVL") == 0.0
    assert pid.init_args.get("SVH") == 1.2
    assert pid.init_args.get("MVL") == 0.0
    assert pid.init_args.get("MVH") == 100.0
    # 初值
    assert pid.init_args.get("PV") == 0.15
    assert pid.init_args.get("SV") == 0.8
    assert pid.init_args.get("MV") == 0.0


def test_two_tank_pid_params_correct():
    """二阶水箱 PID 参数与量程配置正确。"""
    parser = DSLParser()
    config = parser.parse_file("config/单阀门二阶水箱.yaml")
    pid = next(item for item in config.program if item.name == "pid2")

    assert pid.init_args.get("PB") == 30.0
    assert pid.init_args.get("TI") == 90.0
    assert pid.init_args.get("TD") == 20.0
    assert pid.init_args.get("KD") == 10.0
    assert pid.init_args.get("MODE") == 5
    assert pid.init_args.get("SWPN") == 1
    # 量程
    assert pid.init_args.get("SVSCL") == 0.0
    assert pid.init_args.get("SVSCH") == 1.2
    assert pid.init_args.get("MVSCL") == 0.0
    assert pid.init_args.get("MVSCH") == 100.0
    # 初值
    assert pid.init_args.get("PV") == 0.10
    assert pid.init_args.get("SV") == 0.8
    assert pid.init_args.get("MV") == 0.0


# ----------------------------------------------------------------------
# 5. 运行过程中 PV/SV/MV 均为有限值
# ----------------------------------------------------------------------
def test_single_tank_all_values_finite():
    """单水箱运行 1500 周期，PV/SV/MV 始终为有限值。"""
    engine = _build_engine("config/tank_structured.yaml")
    snapshots = _run_cycles(engine, 1500)
    for s in snapshots:
        assert math.isfinite(s.get("pid1.PV", float("nan"))), "PV 非有限"
        assert math.isfinite(s.get("pid1.SV", float("nan"))), "SV 非有限"
        assert math.isfinite(s.get("pid1.MV", float("nan"))), "MV 非有限"
        assert math.isfinite(s.get("tank_1.level", float("nan"))), "level 非有限"


def test_two_tank_all_values_finite():
    """二阶水箱运行 1500 周期，PV/SV/MV 与两个水箱液位始终为有限值。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml")
    snapshots = _run_cycles(engine, 1500)
    for s in snapshots:
        assert math.isfinite(s.get("pid2.PV", float("nan"))), "PV 非有限"
        assert math.isfinite(s.get("pid2.SV", float("nan"))), "SV 非有限"
        assert math.isfinite(s.get("pid2.MV", float("nan"))), "MV 非有限"
        assert math.isfinite(s.get("tank_1.level", float("nan"))), "上游 level 非有限"
        assert math.isfinite(s.get("tank_2.level", float("nan"))), "下游 level 非有限"


# ----------------------------------------------------------------------
# 6. 单水箱响应时间、峰值与最终稳态范围
# ----------------------------------------------------------------------
def test_single_tank_response_acceptance():
    """单水箱满足响应时间、峰值和最终稳态验收范围。"""
    engine = _build_engine("config/tank_structured.yaml")
    snapshots = _run_cycles(engine, 1500)

    levels = [s["tank_1.level"] for s in snapshots]
    mvs = [s["pid1.MV"] for s in snapshots]

    target = 0.8

    # 到达目标 90%（0.72）：200~300 周期
    reach_90 = _first_cycle_reaching(levels, target * 0.9)
    assert reach_90 is not None, "未到达 90%"
    assert 200 <= reach_90 <= 300, f"到达 90% 周期超出范围: {reach_90}"

    # 最高液位出现时间：400~600 周期
    peak_idx = _peak_cycle(levels)
    assert 400 <= peak_idx <= 600, f"峰值周期超出范围: {peak_idx}"

    # 最高液位：0.85~0.90m
    peak_level = levels[peak_idx]
    assert 0.85 <= peak_level <= 0.90, f"峰值液位超出范围: {peak_level}"

    # 进入并保持 ±2%：750~900 周期
    stable_2 = _first_cycle_stable_in_band(levels, target, 2)
    assert stable_2 is not None, "未进入 ±2% 稳定带"
    assert 750 <= stable_2 <= 900, f"±2% 稳定周期超出范围: {stable_2}"

    # 进入并保持 ±1%：850~1000 周期
    stable_1 = _first_cycle_stable_in_band(levels, target, 1)
    assert stable_1 is not None, "未进入 ±1% 稳定带"
    assert 850 <= stable_1 <= 1000, f"±1% 稳定周期超出范围: {stable_1}"

    # 最终液位：0.79~0.81m
    final_level = levels[-1]
    assert 0.79 <= final_level <= 0.81, f"最终液位超出范围: {final_level}"

    # 最终 MV：38%~41%
    final_mv = mvs[-1]
    assert 38.0 <= final_mv <= 41.0, f"最终 MV 超出范围: {final_mv}"


# ----------------------------------------------------------------------
# 7. 二阶水箱响应时间、峰值与最终稳态范围
# ----------------------------------------------------------------------
def test_two_tank_response_acceptance():
    """二阶水箱满足响应时间、峰值和最终稳态验收范围。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml")
    snapshots = _run_cycles(engine, 1500)

    levels_down = [s["tank_2.level"] for s in snapshots]
    levels_up = [s["tank_1.level"] for s in snapshots]
    mvs = [s["pid2.MV"] for s in snapshots]

    target = 0.8

    # 下游液位到达目标 90%（0.72）：250~400 周期
    reach_90 = _first_cycle_reaching(levels_down, target * 0.9)
    assert reach_90 is not None, "下游未到达 90%"
    assert 250 <= reach_90 <= 400, f"下游到达 90% 周期超出范围: {reach_90}"

    # 下游最高液位出现时间：400~600 周期
    peak_idx = _peak_cycle(levels_down)
    assert 400 <= peak_idx <= 600, f"下游峰值周期超出范围: {peak_idx}"

    # 下游最高液位：0.83~0.88m
    peak_level = levels_down[peak_idx]
    assert 0.83 <= peak_level <= 0.88, f"下游峰值液位超出范围: {peak_level}"

    # 进入并保持 ±2%：800~950 周期
    stable_2 = _first_cycle_stable_in_band(levels_down, target, 2)
    assert stable_2 is not None, "下游未进入 ±2% 稳定带"
    assert 800 <= stable_2 <= 950, f"下游 ±2% 稳定周期超出范围: {stable_2}"

    # 进入并保持 ±1%：900~1050 周期
    stable_1 = _first_cycle_stable_in_band(levels_down, target, 1)
    assert stable_1 is not None, "下游未进入 ±1% 稳定带"
    assert 900 <= stable_1 <= 1050, f"下游 ±1% 稳定周期超出范围: {stable_1}"

    # 最终下游液位：0.79~0.81m
    final_down = levels_down[-1]
    assert 0.79 <= final_down <= 0.81, f"最终下游液位超出范围: {final_down}"

    # 最终上游液位：0.50~0.53m
    final_up = levels_up[-1]
    assert 0.50 <= final_up <= 0.53, f"最终上游液位超出范围: {final_up}"

    # 最终 MV：64%~68%
    final_mv = mvs[-1]
    assert 64.0 <= final_mv <= 68.0, f"最终 MV 超出范围: {final_mv}"


# ----------------------------------------------------------------------
# 8. 二阶水箱上游液位不触碰高度上限
# ----------------------------------------------------------------------
def test_two_tank_upstream_below_height_limit():
    """二阶水箱上游液位全程小于 1.0m，不触碰 height=1.2m 模型削顶上限。"""
    engine = _build_engine("config/单阀门二阶水箱.yaml")
    snapshots = _run_cycles(engine, 1500)

    levels_up = [s["tank_1.level"] for s in snapshots]
    max_up = max(levels_up)
    # 验收要求上游最高液位必须小于 1.0m（远低于模型削顶 1.2m）
    assert max_up < 1.0, f"上游最高液位 {max_up} 超过 1.0m"
    # 同时确认没有触碰模型削顶上限
    assert max_up < 1.2, f"上游液位 {max_up} 触碰模型 height=1.2m 削顶上限"


# ----------------------------------------------------------------------
# 9. old_version 不进入正常配置发现
# ----------------------------------------------------------------------
def test_old_version_not_discovered():
    """discover_configs 应跳过 old_version 目录，不返回其中的历史文件。"""
    # standalone_main 在项目根目录
    sys.path.insert(0, str(_project_root))
    from standalone_main import discover_configs

    configs = discover_configs(_project_root / "config")

    # 不应包含任何 old_version 路径
    for name, path in configs.items():
        assert "old_version" not in path.parts, (
            f"配置 {name} 来自 old_version 目录: {path}"
        )

    # 正式配置应包含 tank_structured 和 单阀门二阶水箱
    assert "tank_structured" in configs
    assert "单阀门二阶水箱" in configs
    assert "单阀门二阶水箱开环辨识" in configs
