"""
乙醇—水连续精馏塔控制 DSL 测试（阶段 E，spec §15.2）。

覆盖：
1. 两份 DSL 均可解析
2. 模型注册名正确
3. 拓扑顺序确定（多次解析顺序一致）
4. 只有 column_1.execute_first=true
5. 所有 PID 标准位号存在
6. 所有串级副回路 MODE=6、CAS=1
7. 主回路 MV 量程与副回路 CSV 量程一致
8. 控制方向通过小扰动验证
9. UA/Engine 外部写 SV 能改变真实控制目标
10. 5 秒采样不修改位号名
11. 运行过程中 PV/SV/MV 始终有限
12. 扰动恢复测试
"""

import math
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 触发组件注册
import components.programs  # noqa: F401
from components.programs.ethanol_water_distillation import ETHANOL_WATER_DISTILLATION
from components.programs.pid import PID
from controller.instance import InstanceRegistry
from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from controller.clock import ClockMode


# ====================================================================
# 路径与常量
# ====================================================================
BASIC_DSL = "config/乙醇水连续精馏_基础控制.yaml"
QUALITY_DSL = "config/乙醇水连续精馏_质量控制.yaml"

PID_STANDARD_TAGS = [
    "PV", "SV", "CSV", "MV", "PB", "TI", "TD", "KD",
    "MODE", "AUTO", "CAS", "SWPN",
    "SVSCH", "SVSCL", "MVSCH", "MVSCL", "SVH", "SVL", "MVH", "MVL",
]


# ====================================================================
# 辅助
# ====================================================================
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


def _get_pid_params(config, name: str) -> dict:
    """从配置中获取指定 PID 的 init_args。"""
    for item in config.program:
        if item.name == name:
            return item.init_args
    raise KeyError(f"PID {name} 不存在")


# ====================================================================
# 1. 两份 DSL 均可解析
# ====================================================================
def test_basic_control_dsl_parses():
    """基础控制 DSL 能解析。"""
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    assert len(config.program) > 0
    names = {item.name for item in config.program}
    # 必含的节点
    required = {
        "feed_ethanol_wt", "feed_temperature_c", "column_1",
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_temp_pid", "reflux_flow_pid",
        "bottom_temp_pid", "steam_flow_pid",
    }
    assert required.issubset(names), f"缺少节点: {required - names}"


def test_quality_control_dsl_parses():
    """质量控制 DSL 能解析。"""
    parser = DSLParser()
    config = parser.parse_file(QUALITY_DSL)
    assert len(config.program) > 0
    names = {item.name for item in config.program}
    required = {
        "feed_ethanol_wt", "feed_temperature_c", "column_1",
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_quality_pid", "reflux_flow_pid",
        "bottom_quality_pid", "steam_flow_pid",
    }
    assert required.issubset(names), f"缺少节点: {required - names}"


# ====================================================================
# 2. 模型注册名正确
# ====================================================================
def test_model_registered():
    """ETHANOL_WATER_DISTILLATION 模型在 InstanceRegistry 中正确注册。"""
    assert InstanceRegistry.get_model("ETHANOL_WATER_DISTILLATION") is ETHANOL_WATER_DISTILLATION


def test_column_uses_registered_model():
    """两份 DSL 的 column_1 节点 type 为 ETHANOL_WATER_DISTILLATION。"""
    parser = DSLParser()
    for path in (BASIC_DSL, QUALITY_DSL):
        config = parser.parse_file(path)
        column = next(item for item in config.program if item.name == "column_1")
        assert column.type.upper() == "ETHANOL_WATER_DISTILLATION", (
            f"{path} column_1.type 应为 ETHANOL_WATER_DISTILLATION，实际: {column.type}"
        )


# ====================================================================
# 3. 拓扑顺序确定
# ====================================================================
def test_topology_order_deterministic():
    """多次解析得到的拓扑顺序一致（确定性）。"""
    parser = DSLParser()
    orders_basic = [
        [item.name for item in parser.parse_file(BASIC_DSL).program]
        for _ in range(3)
    ]
    orders_quality = [
        [item.name for item in parser.parse_file(QUALITY_DSL).program]
        for _ in range(3)
    ]
    assert orders_basic[0] == orders_basic[1] == orders_basic[2], (
        f"基础 DSL 拓扑顺序不确定: {orders_basic}"
    )
    assert orders_quality[0] == orders_quality[1] == orders_quality[2], (
        f"质量 DSL 拓扑顺序不确定: {orders_quality}"
    )


def test_basic_topology_column_first():
    """
    基础 DSL 拓扑：column_1 因 execute_first=True，应在所有 PID 之前执行。
    """
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    names = [item.name for item in config.program]
    column_idx = names.index("column_1")
    # 所有 PID 都在 column_1 之后
    pid_names = {
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_temp_pid", "reflux_flow_pid",
        "bottom_temp_pid", "steam_flow_pid",
    }
    for pid_name in pid_names:
        assert names.index(pid_name) > column_idx, (
            f"{pid_name} 应在 column_1 之后执行"
        )


def test_quality_topology_column_first():
    """质量 DSL 拓扑：column_1 因 execute_first=True，应在所有 PID 之前执行。"""
    parser = DSLParser()
    config = parser.parse_file(QUALITY_DSL)
    names = [item.name for item in config.program]
    column_idx = names.index("column_1")
    pid_names = {
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_quality_pid", "reflux_flow_pid",
        "bottom_quality_pid", "steam_flow_pid",
    }
    for pid_name in pid_names:
        assert names.index(pid_name) > column_idx, (
            f"{pid_name} 应在 column_1 之后执行"
        )


def test_basic_cascade_topological_order():
    """
    串级副回路应在主回路之后执行（副回路读取主回路 MV 作为 CSV）。
    """
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    names = [item.name for item in config.program]
    # reflux_flow_pid 依赖 top_temp_pid.MV
    assert names.index("reflux_flow_pid") > names.index("top_temp_pid"), (
        "reflux_flow_pid 应在 top_temp_pid 之后"
    )
    # steam_flow_pid 依赖 bottom_temp_pid.MV
    assert names.index("steam_flow_pid") > names.index("bottom_temp_pid"), (
        "steam_flow_pid 应在 bottom_temp_pid 之后"
    )


def test_quality_cascade_topological_order():
    """质量 DSL 串级副回路应在主回路之后执行。"""
    parser = DSLParser()
    config = parser.parse_file(QUALITY_DSL)
    names = [item.name for item in config.program]
    assert names.index("reflux_flow_pid") > names.index("top_quality_pid")
    assert names.index("steam_flow_pid") > names.index("bottom_quality_pid")


# ====================================================================
# 4. 只有 column_1.execute_first=true
# ====================================================================
def test_only_column_has_execute_first():
    """两份 DSL 中只有 column_1 设置了 execute_first: true。"""
    parser = DSLParser()
    for path in (BASIC_DSL, QUALITY_DSL):
        config = parser.parse_file(path)
        execute_first_nodes = [item.name for item in config.program if item.execute_first]
        assert execute_first_nodes == ["column_1"], (
            f"{path} 应只有 column_1.execute_first=True，实际: {execute_first_nodes}"
        )


# ====================================================================
# 5. 所有 PID 标准位号存在
# ====================================================================
def test_pid_standard_attributes_exist():
    """运行后所有 PID 标准位号都出现在快照中。"""
    engine = _build_engine(BASIC_DSL)
    snapshots = _run_cycles(engine, 2)
    snap = snapshots[-1]
    pid_names = [
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_temp_pid", "reflux_flow_pid",
        "bottom_temp_pid", "steam_flow_pid",
    ]
    for pid_name in pid_names:
        for tag in PID_STANDARD_TAGS:
            key = f"{pid_name}.{tag}"
            assert key in snap, f"快照缺少标准位号: {key}"
            v = snap[key]
            assert math.isfinite(float(v)) or tag in ("AUTO", "CAS"), (
                f"{key} 非有限值: {v}"
            )


# ====================================================================
# 6. 所有串级副回路 MODE=6、CAS=1
# ====================================================================
def test_cascade_slaves_mode_and_cas():
    """
    串级副回路 MODE=6 (CAS)、CAS=1（运行后）。
    基础 DSL：reflux_flow_pid, steam_flow_pid
    质量 DSL：reflux_flow_pid, steam_flow_pid
    """
    for path in (BASIC_DSL, QUALITY_DSL):
        parser = DSLParser()
        config = parser.parse_file(path)
        # 解析阶段检查 init_args.MODE=6
        for slave_name in ("reflux_flow_pid", "steam_flow_pid"):
            params = _get_pid_params(config, slave_name)
            assert params.get("MODE") == 6, (
                f"{path} {slave_name}.MODE 应为 6，实际: {params.get('MODE')}"
            )
        # 运行后检查 CAS=1
        engine = _build_engine(path)
        snaps = _run_cycles(engine, 2)
        snap = snaps[-1]
        for slave_name in ("reflux_flow_pid", "steam_flow_pid"):
            cas_key = f"{slave_name}.CAS"
            assert int(snap[cas_key]) == 1, (
                f"{path} {slave_name}.CAS 应为 1，实际: {snap[cas_key]}"
            )
            mode_key = f"{slave_name}.MODE"
            assert int(snap[mode_key]) == 6, (
                f"{path} {slave_name}.MODE 应为 6，实际: {snap[mode_key]}"
            )


def test_master_loops_mode_5():
    """主回路（4 单回路 + 2 串级主回路）MODE=5 (AUTO)。"""
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    master_names = [
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_temp_pid", "bottom_temp_pid",
    ]
    for name in master_names:
        params = _get_pid_params(config, name)
        assert params.get("MODE") == 5, (
            f"{name}.MODE 应为 5，实际: {params.get('MODE')}"
        )


# ====================================================================
# 7. 主回路 MV 量程与副回路 CSV 量程一致
# ====================================================================
def test_master_mv_range_matches_slave_csv_range():
    """
    串级主回路 MV 量程必须与副回路 SV/CSV 量程完全一致。
    spec §8.6：正式 DSL 中主回路输出量程必须与副回路 SV/CSV 量程完全一致。
    """
    parser = DSLParser()
    for path, master_slave_pairs in (
        (BASIC_DSL, [("top_temp_pid", "reflux_flow_pid"), ("bottom_temp_pid", "steam_flow_pid")]),
        (QUALITY_DSL, [("top_quality_pid", "reflux_flow_pid"), ("bottom_quality_pid", "steam_flow_pid")]),
    ):
        config = parser.parse_file(path)
        for master_name, slave_name in master_slave_pairs:
            master = _get_pid_params(config, master_name)
            slave = _get_pid_params(config, slave_name)
            # 主回路 MVSCL/MVSCH 必须等于副回路 SVSCL/SVSCH
            assert master["MVSCL"] == slave["SVSCL"], (
                f"{path} {master_name}.MVSCL={master['MVSCL']} != "
                f"{slave_name}.SVSCL={slave['SVSCL']}"
            )
            assert master["MVSCH"] == slave["SVSCH"], (
                f"{path} {master_name}.MVSCH={master['MVSCH']} != "
                f"{slave_name}.SVSCH={slave['SVSCH']}"
            )


# ====================================================================
# 8. 控制方向通过小扰动验证
# ====================================================================
# 实现说明：
# PID 是增量式（ΔMV = (100/PB)*(ΔE + Ts/TI*E + ΔU)），在 DSL 闭环中
# SV 阶跃会让 ΔE 瞬时大幅变化，MV 短期可能反向。要验证"方向配置正确"，
# 最可靠的方法是从 engine 取出 PID 实例，直接在固定 PV 下施加 SV 扰动，
# 观察 PID 单步响应方向。这样既验证了 DSL 中 SWPN 配置，又避开闭环动态。
def _test_pid_direction_via_instance(
    dsl_path: str, pid_name: str, pv: float, sv: float, expect_mv_increase: bool
):
    """
    从 DSL 构建的 engine 中取出 PID 实例，直接验证方向。

    通过重置 PID 内部状态（_initialized=False 等），让 execute 走冷启动分支，
    p_delta = error_pct（而非 error_pct - _prev_error_pct），单步响应方向明确。

    Args:
        dsl_path: DSL 文件路径
        pid_name: PID 实例名
        pv: 强制设置的 PV 值
        sv: 强制设置的 SV 值
        expect_mv_increase: 期望 MV 是否增加
    """
    engine = _build_engine(dsl_path)
    _run_cycles(engine, 2)  # 让实例初始化
    pid = engine._instances[pid_name]
    # 强制 PV/SV/MODE，使 error 朝期望方向
    pid.PV = pv
    pid.SV = sv
    pid.MODE = 5
    # 重置 PID 内部状态，让单步响应只反映本次 error（冷启动路径）
    pid.MV = 50.0  # 起始 MV 居中
    pid._last_valid_mv = 50.0
    pid._mv_pct = pid._engineering_mv_to_pct(50.0)
    pid._prev_error_pct = 0.0
    pid._prev_derivative_state = 0.0
    pid._sv_scale_changed = False
    pid._initialized = False  # 走冷启动分支：p_delta = error_pct
    pid._previous_mode = 0
    # 单步执行（不传 inputs，PID 用实例属性）
    pid.execute()
    mv_after = float(pid.MV)
    if expect_mv_increase:
        assert mv_after > 50.0, (
            f"{pid_name}: PV={pv}, SV={sv}, 期望 MV 增加，实际 {50.0} -> {mv_after}"
        )
    else:
        assert mv_after < 50.0, (
            f"{pid_name}: PV={pv}, SV={sv}, 期望 MV 减小，实际 {50.0} -> {mv_after}"
        )


def test_feed_flow_pid_direction():
    """进料流量 PID：SWPN=1，SV>PV 时 MV 增加。"""
    _test_pid_direction_via_instance(BASIC_DSL, "feed_flow_pid", pv=80.0, sv=100.0, expect_mv_increase=True)


def test_pressure_pid_direction():
    """塔顶压力 PID：SWPN=0，PV>SV 时 MV 增加。"""
    _test_pid_direction_via_instance(BASIC_DSL, "pressure_pid", pv=110.0, sv=100.0, expect_mv_increase=True)


def test_reflux_drum_level_pid_direction():
    """回流罐液位 PID：SWPN=0，PV>SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        BASIC_DSL, "reflux_drum_level_pid", pv=70.0, sv=50.0, expect_mv_increase=True
    )


def test_reboiler_level_pid_direction():
    """塔釜液位 PID：SWPN=0，PV>SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        BASIC_DSL, "reboiler_level_pid", pv=70.0, sv=50.0, expect_mv_increase=True
    )


def test_top_temp_pid_direction():
    """上部温度主回路：SWPN=0，PV>SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        BASIC_DSL, "top_temp_pid", pv=85.0, sv=75.0, expect_mv_increase=True
    )


def test_bottom_temp_pid_direction():
    """下部温度主回路：SWPN=1，PV<SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        BASIC_DSL, "bottom_temp_pid", pv=85.0, sv=95.0, expect_mv_increase=True
    )


def test_top_quality_pid_direction():
    """塔顶浓度主回路（质量 DSL）：SWPN=1，PV<SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        QUALITY_DSL, "top_quality_pid", pv=0.80, sv=0.85, expect_mv_increase=True
    )


def test_bottom_quality_pid_direction():
    """塔底浓度主回路（质量 DSL）：SWPN=0，PV>SV 时 MV 增加。"""
    _test_pid_direction_via_instance(
        QUALITY_DSL, "bottom_quality_pid", pv=0.025, sv=0.015, expect_mv_increase=True
    )


def test_cascade_slave_direction():
    """串级副回路（reflux_flow_pid, steam_flow_pid）：SWPN=1，PV<CSV 时 MV 增加。"""
    for slave_name in ("reflux_flow_pid", "steam_flow_pid"):
        _test_pid_direction_via_instance(
            BASIC_DSL, slave_name, pv=50.0, sv=80.0, expect_mv_increase=True
        )


# ====================================================================
# 9. UA/Engine 外部写 SV 能改变真实控制目标
# ====================================================================
def test_external_sv_override_changes_target():
    """
    通过 engine.override_variable 写 SV，下一周期 PID.SV 真实变化。
    """
    engine = _build_engine(BASIC_DSL)
    _run_cycles(engine, 3)
    sv_before = float(engine.vars.get("feed_flow_pid.SV"))
    new_sv = sv_before + 15.0
    engine.override_variable("feed_flow_pid.SV", new_sv)
    _run_cycles(engine, 2)
    sv_after = float(engine.vars.get("feed_flow_pid.SV"))
    assert abs(sv_after - new_sv) < 1e-6, (
        f"外部写 SV 未生效: before={sv_before}, target={new_sv}, after={sv_after}"
    )


def test_external_mode_override_changes_mode():
    """通过 engine.override_variable 写 MODE，下一周期 PID.MODE 真实变化。"""
    engine = _build_engine(BASIC_DSL)
    _run_cycles(engine, 3)
    engine.override_variable("feed_flow_pid.MODE", 1)  # MAN
    _run_cycles(engine, 2)
    mode_after = int(engine.vars.get("feed_flow_pid.MODE"))
    assert mode_after == 1, f"外部写 MODE 未生效: {mode_after}"


# ====================================================================
# 10. 5 秒采样不修改位号名
# ====================================================================
def test_sample_interval_does_not_rename_tags():
    """
    spec §7.2: 5 秒采样后仍然叫 PV/SV/MV，不得增加 _5s、_mean、-sample 等后缀。

    验证：sample_interval=5.0 时，快照中位号名与基础位号完全一致，
    没有 _5s/_mean/-sample 等后缀。
    """
    parser = DSLParser()
    for path in (BASIC_DSL, QUALITY_DSL):
        config = parser.parse_file(path)
        # 确认 DSL 中 sample_interval = 5.0
        assert config.clock.sample_interval == 5.0, (
            f"{path} sample_interval 应为 5.0，实际: {config.clock.sample_interval}"
        )
        # 运行 22 周期（cycle_time=0.5, sample_interval=5.0 → 每 10 周期采样一次）
        # 覆盖至少 2 个采样点（cycle 0 和 cycle 10；cycle 20 在第 21 周期）
        engine = _build_engine(path)
        snaps = _run_cycles(engine, 22)
        sample_flags = [s.get("need_sample", False) for s in snaps]
        assert sum(sample_flags) >= 2, f"{path} 采样点数量过少: {sum(sample_flags)}"
        # 检查工艺/PID 位号名无任何采样后缀
        # spec §7.2: 5 秒采样后仍然叫 PV/SV/MV，不得增加 _5s、_mean、-sample 等后缀
        # 注意：engine 内置 key（need_sample/cycle_count/sim_time 等）非工艺位号，跳过
        forbidden_suffixes = ("_5s", "_mean", "-sample", "_10c", "_sampled")
        engine_internal_keys = {
            "need_sample", "cycle_count", "sim_time", "time_str",
            "exec_ratio", "_safe_state", "_consecutive_failures",
        }
        for snap in snaps:
            for key in snap.keys():
                if key in engine_internal_keys:
                    continue
                for suffix in forbidden_suffixes:
                    assert not key.endswith(suffix), (
                        f"{path} 位号 {key} 含禁止后缀 {suffix}"
                    )
        # 标准位号必须保持原名
        snap = snaps[-1]
        for pid_name in ("feed_flow_pid", "pressure_pid"):
            for tag in ("PV", "SV", "MV", "MODE"):
                key = f"{pid_name}.{tag}"
                assert key in snap, f"{path} 缺少标准位号 {key}"


# ====================================================================
# 11. 运行过程中所有值有限
# ====================================================================
def test_basic_dsl_all_values_finite():
    """基础 DSL 运行 200 周期，所有 PID 和关键工艺位号始终有限。"""
    engine = _build_engine(BASIC_DSL)
    snaps = _run_cycles(engine, 200)
    pid_names = [
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_temp_pid", "reflux_flow_pid",
        "bottom_temp_pid", "steam_flow_pid",
    ]
    column_attrs = [
        "top_pressure_kpa", "bottom_pressure_kpa",
        "top_temperature_c", "bottom_temperature_c",
        "feed_flow_kg_h", "reflux_flow_kg_h",
        "distillate_flow_kg_h", "bottoms_flow_kg_h",
        "vapor_boilup_kg_h",
        "reflux_drum_level_pct", "reboiler_level_pct",
    ]
    for i, snap in enumerate(snaps):
        for pid in pid_names:
            for tag in ("PV", "SV", "MV", "CSV"):
                key = f"{pid}.{tag}"
                if key in snap:
                    v = snap[key]
                    assert math.isfinite(float(v)), f"周期 {i} {key} 非有限: {v}"
        for attr in column_attrs:
            key = f"column_1.{attr}"
            if key in snap:
                v = snap[key]
                assert math.isfinite(float(v)), f"周期 {i} {key} 非有限: {v}"


def test_quality_dsl_all_values_finite():
    """质量 DSL 运行 200 周期，所有 PID 和关键工艺位号始终有限。"""
    engine = _build_engine(QUALITY_DSL)
    snaps = _run_cycles(engine, 200)
    pid_names = [
        "feed_flow_pid", "pressure_pid",
        "reflux_drum_level_pid", "reboiler_level_pid",
        "top_quality_pid", "reflux_flow_pid",
        "bottom_quality_pid", "steam_flow_pid",
    ]
    for i, snap in enumerate(snaps):
        for pid in pid_names:
            for tag in ("PV", "SV", "MV", "CSV"):
                key = f"{pid}.{tag}"
                if key in snap:
                    v = snap[key]
                    assert math.isfinite(float(v)), f"周期 {i} {key} 非有限: {v}"


# ====================================================================
# 12. 扰动恢复测试
# ====================================================================
def test_basic_dsl_perturbation_recovery():
    """
    阶段 E 交付物：扰动恢复测试。

    流程：
    1. 预热到接近稳态
    2. 施加 SV 阶跃扰动
    3. 观察响应方向正确（MV 朝期望方向变化）
    """
    engine = _build_engine(BASIC_DSL)
    _run_cycles(engine, 20)  # 预热

    # 记录扰动前 MV
    mv_before = float(engine.vars.get("feed_flow_pid.MV"))
    sv_before = float(engine.vars.get("feed_flow_pid.SV"))

    # 施加 +20% SV 阶跃
    new_sv = sv_before * 1.2
    engine.override_variable("feed_flow_pid.SV", new_sv)
    _run_cycles(engine, 10)

    mv_after = float(engine.vars.get("feed_flow_pid.MV"))
    # SWPN=1: SV 升高 → error 增大 → MV 增加（开大进料阀）
    assert mv_after > mv_before, (
        f"扰动后 MV 应增加: before={mv_before}, after={mv_after}, SV={sv_before} -> {new_sv}"
    )
    # MV 应在合理范围 [0, 100]
    assert 0.0 <= mv_after <= 100.0, f"MV 超出物理范围: {mv_after}"


def test_basic_dsl_long_run_stable():
    """
    阶段 E 交付物：长周期运行稳定性（500 周期无 NaN/Inf）。
    """
    engine = _build_engine(BASIC_DSL)
    snaps = _run_cycles(engine, 500)
    assert len(snaps) == 500
    # 关键位号无 NaN/Inf
    for i, snap in enumerate(snaps):
        for key in (
            "column_1.top_pressure_kpa",
            "column_1.reflux_drum_level_pct",
            "column_1.reboiler_level_pct",
            "feed_flow_pid.MV", "pressure_pid.MV",
        ):
            v = snap.get(key, 0.0)
            assert math.isfinite(float(v)), f"周期 {i} {key} 非有限: {v}"


# ====================================================================
# 13. PID 参数与 spec §8.5 整定值一致
# ====================================================================
def test_basic_pid_tuning_matches_spec():
    """基础 DSL PID 整定值与 spec §8.5 一致。"""
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    expected = {
        "feed_flow_pid":         (100.0,  10.0, 0.0, 5, 1),
        "pressure_pid":          (100.0,  30.0, 0.0, 5, 0),
        "reflux_drum_level_pid": (100.0, 300.0, 0.0, 5, 0),
        "reboiler_level_pid":    (100.0, 300.0, 0.0, 5, 0),
        "top_temp_pid":          (100.0, 300.0, 0.0, 5, 0),
        "reflux_flow_pid":       (100.0,  10.0, 0.0, 6, 1),
        "bottom_temp_pid":       (100.0, 300.0, 0.0, 5, 1),
        "steam_flow_pid":        (100.0,  15.0, 0.0, 6, 1),
    }
    for name, (pb, ti, td, mode, swpn) in expected.items():
        params = _get_pid_params(config, name)
        assert params["PB"] == pb, f"{name}.PB 应为 {pb}, 实际 {params['PB']}"
        assert params["TI"] == ti, f"{name}.TI 应为 {ti}, 实际 {params['TI']}"
        assert params["TD"] == td, f"{name}.TD 应为 {td}, 实际 {params['TD']}"
        assert params["MODE"] == mode, f"{name}.MODE 应为 {mode}, 实际 {params['MODE']}"
        assert params["SWPN"] == swpn, f"{name}.SWPN 应为 {swpn}, 实际 {params['SWPN']}"


def test_quality_pid_tuning_matches_spec():
    """质量 DSL PID 整定值与 spec §8.5 一致。"""
    parser = DSLParser()
    config = parser.parse_file(QUALITY_DSL)
    expected = {
        "feed_flow_pid":         (100.0,  10.0, 0.0, 5, 1),
        "pressure_pid":          (100.0,  30.0, 0.0, 5, 0),
        "reflux_drum_level_pid": (100.0, 300.0, 0.0, 5, 0),
        "reboiler_level_pid":    (100.0, 300.0, 0.0, 5, 0),
        "top_quality_pid":       (100.0, 900.0, 0.0, 5, 1),
        "reflux_flow_pid":       (100.0,  10.0, 0.0, 6, 1),
        "bottom_quality_pid":    (100.0, 900.0, 0.0, 5, 0),
        "steam_flow_pid":        (100.0,  15.0, 0.0, 6, 1),
    }
    for name, (pb, ti, td, mode, swpn) in expected.items():
        params = _get_pid_params(config, name)
        assert params["PB"] == pb, f"{name}.PB 应为 {pb}, 实际 {params['PB']}"
        assert params["TI"] == ti, f"{name}.TI 应为 {ti}, 实际 {params['TI']}"
        assert params["TD"] == td, f"{name}.TD 应为 {td}, 实际 {params['TD']}"
        assert params["MODE"] == mode, f"{name}.MODE 应为 {mode}, 实际 {params['MODE']}"
        assert params["SWPN"] == swpn, f"{name}.SWPN 应为 {swpn}, 实际 {params['SWPN']}"


# ====================================================================
# 14. column_1 inputs 连接正确
# ====================================================================
def test_column_inputs_correct():
    """column_1 的六个阀位输入连接到正确 PID 的 MV。"""
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    column = next(item for item in config.program if item.name == "column_1")
    inputs = column.inputs
    assert inputs["feed_valve_pct"] == "feed_flow_pid.MV"
    assert inputs["reflux_valve_pct"] == "reflux_flow_pid.MV"
    assert inputs["distillate_valve_pct"] == "reflux_drum_level_pid.MV"
    assert inputs["bottoms_valve_pct"] == "reboiler_level_pid.MV"
    assert inputs["steam_valve_pct"] == "steam_flow_pid.MV"
    assert inputs["cooling_valve_pct"] == "pressure_pid.MV"


def test_cascade_csv_connections():
    """串级副回路 CSV 连接到主回路 MV。"""
    parser = DSLParser()
    config = parser.parse_file(BASIC_DSL)
    reflux = next(item for item in config.program if item.name == "reflux_flow_pid")
    steam = next(item for item in config.program if item.name == "steam_flow_pid")
    assert reflux.inputs["CSV"] == "top_temp_pid.MV"
    assert steam.inputs["CSV"] == "bottom_temp_pid.MV"

    config_q = parser.parse_file(QUALITY_DSL)
    reflux_q = next(item for item in config_q.program if item.name == "reflux_flow_pid")
    steam_q = next(item for item in config_q.program if item.name == "steam_flow_pid")
    assert reflux_q.inputs["CSV"] == "top_quality_pid.MV"
    assert steam_q.inputs["CSV"] == "bottom_quality_pid.MV"
