"""
乙醇—水热力学后端单元测试（阶段 A）。

测试覆盖：
1. 纯组分分子量常数
2. 质量/摩尔分数参考值
3. 质量/摩尔分数往返
4. Antoine 蒸气压有限性、单调性
5. NRTL 参数方向（T=298.15 K）
6. 纯水泡点
7. 纯乙醇泡点
8. 23 点 VLE 数据集误差指标
9. 共沸点位置与穿越方向
10. 稠密网格有限性与有界性
11. previous_temperature_k 不改变最终解
12. 非法输入抛 ValueError

数据来源：Arce et al., Fluid Phase Equilibria 122 (1996) 117–129.
NRTL 参数来源：SRNL-STI-2021-00391, Table 1.
"""

import math
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from components.thermo.ethanol_water import (
    MW_WATER_KG_PER_KMOL,
    MW_ETHANOL_KG_PER_KMOL,
    saturation_pressure_kpa,
    nrtl_activity_coefficients,
    bubble_point_temperature,
    ethanol_mass_fraction_to_mole_fraction,
    ethanol_mole_fraction_to_mass_fraction,
    _nrtl_tau,
)


# ====================================================================
# 固定参考数据（不可变，离线可复现）
# ====================================================================

#: VLE 验证压力（kPa(a)），来源 Arce et al. (1996)
VLE_REFERENCE_PRESSURE_KPA: float = 101.32

#: 23 个乙醇—水 VLE 实验点 (x_ethanol_liquid, y_ethanol_vapor, temperature_k)
#: 来源：Arce et al., Fluid Phase Equilibria 122 (1996) 117–129.
#: 列顺序：(x_ethanol_liquid, y_ethanol_vapor, temperature_k)
VLE_REFERENCE_101_32_KPA = (
    (0.0000, 0.0000, 373.15),
    (0.0317, 0.2573, 366.29),
    (0.0424, 0.3192, 364.32),
    (0.0863, 0.4289, 360.33),
    (0.1300, 0.4830, 358.10),
    (0.1666, 0.5221, 357.16),
    (0.2137, 0.5511, 356.07),
    (0.2930, 0.5847, 354.97),
    (0.3525, 0.6031, 354.50),
    (0.3950, 0.6150, 353.99),
    (0.4531, 0.6412, 353.40),
    (0.5060, 0.6530, 353.01),
    (0.5629, 0.6833, 352.64),
    (0.6142, 0.7056, 352.33),
    (0.6395, 0.7182, 352.15),
    (0.6794, 0.7410, 351.95),
    (0.7240, 0.7683, 351.77),
    (0.7740, 0.7973, 351.57),
    (0.8436, 0.8505, 351.48),
    (0.8612, 0.8649, 351.44),
    (0.9020, 0.9016, 351.42),
    (0.9464, 0.9409, 351.48),
    (1.0000, 1.0000, 351.56),
)


# ====================================================================
# 1. 分子量常数
# ====================================================================
def test_molecular_weight_constants():
    """分子量常数与 NIST 核对值一致。"""
    assert MW_WATER_KG_PER_KMOL == pytest.approx(18.01528, abs=1e-10)
    assert MW_ETHANOL_KG_PER_KMOL == pytest.approx(46.0684, abs=1e-10)


# ====================================================================
# 2. 质量/摩尔分数参考值
# ====================================================================
def test_mass_to_mole_reference_values():
    """spec §7 给出的三个参考转换值。"""
    # w=0.015 → x=0.00591991
    x = ethanol_mass_fraction_to_mole_fraction(0.015)
    assert x == pytest.approx(0.00591991, abs=1e-6)

    # w=0.25 → x=0.11531969
    x = ethanol_mass_fraction_to_mole_fraction(0.25)
    assert x == pytest.approx(0.11531969, abs=1e-6)

    # w=0.85 → x=0.68905289
    x = ethanol_mass_fraction_to_mole_fraction(0.85)
    assert x == pytest.approx(0.68905289, abs=1e-6)


# ====================================================================
# 3. 质量/摩尔分数往返
# ====================================================================
def test_mass_mole_round_trip():
    """质量分数→摩尔分数→质量分数，往返误差 ≤ 1e-12。"""
    for w in [0.0, 0.001, 0.015, 0.1, 0.25, 0.5, 0.68905289, 0.85, 0.95, 1.0]:
        x = ethanol_mass_fraction_to_mole_fraction(w)
        w_back = ethanol_mole_fraction_to_mass_fraction(x)
        assert abs(w_back - w) <= 1e-12, (
            f"往返失败: w={w} → x={x} → w_back={w_back}, 误差={abs(w_back - w)}"
        )


# ====================================================================
# 4. Antoine 蒸气压
# ====================================================================
def test_antoine_pressure_is_finite_and_increases_with_temperature():
    """Antoine 蒸气压有限且随温度单调递增。"""
    temperatures_k = [340.0, 350.0, 360.0, 370.0, 380.0]

    for component in ("water", "ethanol"):
        pressures = [
            saturation_pressure_kpa(component, T) for T in temperatures_k
        ]
        # 全部有限且为正
        for p in pressures:
            assert math.isfinite(p), f"{component} Psat 非有限: {p}"
            assert p > 0.0, f"{component} Psat 非正: {p}"
        # 单调递增
        for i in range(len(pressures) - 1):
            assert pressures[i] < pressures[i + 1], (
                f"{component} Psat 非单调递增: T={temperatures_k[i]} "
                f"P={pressures[i]}, T={temperatures_k[i+1]} P={pressures[i+1]}"
            )

    # 纯水 100°C (373.15 K) 蒸气压应接近 101.325 kPa
    p_water_100c = saturation_pressure_kpa("water", 373.15)
    assert abs(p_water_100c - 101.325) < 2.0, (
        f"水在 100°C 蒸气压应接近 101.325 kPa, 实际 {p_water_100c}"
    )


# ====================================================================
# 5. NRTL 参数方向
# ====================================================================
def test_nrtl_parameter_direction_at_298_15_k():
    """T=298.15 K 时 tau 值必须与 spec §5 给定值逐位匹配。"""
    tau_water_ethanol, tau_ethanol_water = _nrtl_tau(298.15)

    # spec §5 要求的精确值
    assert tau_water_ethanol == pytest.approx(1.4945463692772092, abs=1e-12), (
        f"tau_water_ethanol 方向错误: {tau_water_ethanol}"
    )
    assert tau_ethanol_water == pytest.approx(0.0250880429314104, abs=1e-12), (
        f"tau_ethanol_water 方向错误: {tau_ethanol_water}"
    )

    # 纯组分端点活度系数应为 1
    gamma_water_pure, gamma_ethanol_pure = nrtl_activity_coefficients(0.0, 298.15)
    assert gamma_water_pure == pytest.approx(1.0, abs=1e-10)
    # 乙醇在纯水中的无限稀释活度系数应远大于 1（乙醇-水非理想性强）
    assert gamma_ethanol_pure > 1.0

    gamma_water_pure_e, gamma_ethanol_pure_e = nrtl_activity_coefficients(1.0, 298.15)
    assert gamma_ethanol_pure_e == pytest.approx(1.0, abs=1e-10)
    assert gamma_water_pure_e > 1.0


# ====================================================================
# 6. 纯水泡点
# ====================================================================
def test_pure_water_bubble_point():
    """101.32 kPa 下纯水泡点接近 373.15 K，y_ethanol=0。"""
    T_bubble, y_ethanol = bubble_point_temperature(0.0, VLE_REFERENCE_PRESSURE_KPA)

    # spec §10: 纯水实验端点温度误差 ≤ 0.25 K
    assert abs(T_bubble - 373.15) <= 0.25, (
        f"纯水泡点 {T_bubble} K 偏离 373.15 K 超过 0.25 K"
    )
    # x=0 时 y=0
    assert y_ethanol == pytest.approx(0.0, abs=1e-10)


# ====================================================================
# 7. 纯乙醇泡点
# ====================================================================
def test_pure_ethanol_bubble_point():
    """101.32 kPa 下纯乙醇泡点接近 351.56 K，y_ethanol=1。"""
    T_bubble, y_ethanol = bubble_point_temperature(1.0, VLE_REFERENCE_PRESSURE_KPA)

    # spec §10: 纯乙醇实验端点温度误差 ≤ 0.25 K
    assert abs(T_bubble - 351.56) <= 0.25, (
        f"纯乙醇泡点 {T_bubble} K 偏离 351.56 K 超过 0.25 K"
    )
    # x=1 时 y=1
    assert y_ethanol == pytest.approx(1.0, abs=1e-10)


# ====================================================================
# 8. 23 点 VLE 数据集误差指标
# ====================================================================
def test_vle_reference_dataset_error_metrics():
    """23 点 VLE 误差必须满足 spec §10 验收阈值。"""
    t_errors = []
    y_errors = []

    for x_exp, y_exp, T_exp in VLE_REFERENCE_101_32_KPA:
        T_calc, y_calc = bubble_point_temperature(x_exp, VLE_REFERENCE_PRESSURE_KPA)
        t_errors.append(abs(T_calc - T_exp))
        y_errors.append(abs(y_calc - y_exp))

    t_mae = sum(t_errors) / len(t_errors)
    t_max = max(t_errors)
    y_mae = sum(y_errors) / len(y_errors)
    y_max = max(y_errors)

    # spec §10 验收阈值
    assert t_mae <= 0.30, f"T MAE={t_mae} 超过 0.30 K"
    assert t_max <= 0.60, f"T max={t_max} 超过 0.60 K"
    assert y_mae <= 0.005, f"y MAE={y_mae} 超过 0.005"
    assert y_max <= 0.020, f"y max={y_max} 超过 0.020"

    # 与 spec §9 预期值对比（允许最后几位浮点差异）
    assert t_mae == pytest.approx(0.20847, abs=0.05), (
        f"T MAE={t_mae} 与预期 0.20847 偏差过大，需排查参数方向或单位"
    )
    assert y_mae == pytest.approx(0.0028775, abs=0.001), (
        f"y MAE={y_mae} 与预期 0.0028775 偏差过大，需排查参数方向或单位"
    )


# ====================================================================
# 9. 共沸点位置与穿越方向
# ====================================================================
def test_azeotrope_location_and_crossing_direction():
    """
    共沸点位于 spec §10 要求区间内，且穿越方向正确。

    spec §10:
        0.890 <= x_azeotrope <= 0.900
        351.1 K <= T_azeotrope <= 351.5 K
        abs(y_azeotrope - x_azeotrope) <= 1e-8
    """
    # 在 0.85～0.95 区间细扫，找 y-x 穿越零点
    # x < x_azeo 时 y > x；x > x_azeo 时 y < x
    n_scan = 1001
    x_lo, x_hi = 0.85, 0.95
    dx = (x_hi - x_lo) / (n_scan - 1)

    diff_prev = None
    x_prev = None
    x_cross_lo = None
    x_cross_hi = None
    for i in range(n_scan):
        x = x_lo + i * dx
        _, y = bubble_point_temperature(x, VLE_REFERENCE_PRESSURE_KPA)
        diff = y - x
        if diff_prev is not None and diff_prev * diff < 0.0:
            x_cross_lo = x_prev
            x_cross_hi = x
            break
        diff_prev = diff
        x_prev = x

    assert x_cross_lo is not None and x_cross_hi is not None, (
        "未在 [0.85, 0.95] 找到 y-x 穿越零点，共沸点位置异常"
    )

    # 在穿越区间内二分细化共沸点
    for _ in range(80):
        x_mid = 0.5 * (x_cross_lo + x_cross_hi)
        _, y_mid = bubble_point_temperature(x_mid, VLE_REFERENCE_PRESSURE_KPA)
        diff_mid = y_mid - x_mid
        if abs(diff_mid) < 1e-12:
            break
        _, y_lo = bubble_point_temperature(x_cross_lo, VLE_REFERENCE_PRESSURE_KPA)
        if (y_lo - x_cross_lo) * diff_mid < 0.0:
            x_cross_hi = x_mid
        else:
            x_cross_lo = x_mid

    x_azeo = 0.5 * (x_cross_lo + x_cross_hi)
    T_azeo, y_azeo = bubble_point_temperature(x_azeo, VLE_REFERENCE_PRESSURE_KPA)

    # spec §10 验收区间
    assert 0.890 <= x_azeo <= 0.900, f"共沸点 x={x_azeo} 超出 [0.890, 0.900]"
    assert 351.1 <= T_azeo <= 351.5, f"共沸点 T={T_azeo} K 超出 [351.1, 351.5] K"
    assert abs(y_azeo - x_azeo) <= 1e-8, (
        f"共沸点 |y-x|={abs(y_azeo - x_azeo)} 超过 1e-8"
    )

    # spec §10 穿越方向断言
    _, y_low_x = bubble_point_temperature(0.10, VLE_REFERENCE_PRESSURE_KPA)
    assert y_low_x > 0.10, f"x=0.10 时 y={y_low_x} 应大于 x"

    _, y_high_x = bubble_point_temperature(0.95, VLE_REFERENCE_PRESSURE_KPA)
    assert y_high_x < 0.95, f"x=0.95 时 y={y_high_x} 应小于 x"


# ====================================================================
# 10. 稠密网格有限性与有界性
# ====================================================================
def test_vle_dense_grid_is_finite_and_bounded():
    """x∈[0,1] 上 101 点网格，T/γ/y 全部有限且 0≤y≤1。"""
    n_points = 101
    pressure = VLE_REFERENCE_PRESSURE_KPA

    for i in range(n_points):
        x = i / (n_points - 1)  # 0.0, 0.01, ..., 1.0
        T, y = bubble_point_temperature(x, pressure)
        gamma_water, gamma_ethanol = nrtl_activity_coefficients(x, T)

        assert math.isfinite(T), f"x={x} T 非有限: {T}"
        assert math.isfinite(y), f"x={x} y 非有限: {y}"
        assert math.isfinite(gamma_water), f"x={x} gamma_water 非有限"
        assert math.isfinite(gamma_ethanol), f"x={x} gamma_ethanol 非有限"

        assert 0.0 <= y <= 1.0, f"x={x} y={y} 越出 [0, 1]"
        assert T > 0.0, f"x={x} T={T} 非正"

    # 重复计算同一输入必须稳定到 1e-12
    x_test = 0.5
    T1, y1 = bubble_point_temperature(x_test, pressure)
    T2, y2 = bubble_point_temperature(x_test, pressure)
    assert abs(T1 - T2) <= 1e-12, f"重复计算 T 不稳定: {T1} vs {T2}"
    assert abs(y1 - y2) <= 1e-12, f"重复计算 y 不稳定: {y1} vs {y2}"


# ====================================================================
# 11. previous_temperature_k 不改变最终解
# ====================================================================
def test_bubble_point_previous_temperature_does_not_change_solution():
    """提供 previous_temperature_k 仅用于加速，最终解必须一致。"""
    x_test = 0.3
    pressure = VLE_REFERENCE_PRESSURE_KPA

    # 基准解（不提供 previous）
    T_base, y_base = bubble_point_temperature(x_test, pressure)

    # 提供偏离的 previous（±5K），解必须一致
    # 容差 1e-9 K 与求解器压力残差容差 1e-9 kPa 对应的温度精度一致
    T_with_prev_lo, y_with_prev_lo = bubble_point_temperature(
        x_test, pressure, previous_temperature_k=T_base - 5.0
    )
    T_with_prev_hi, y_with_prev_hi = bubble_point_temperature(
        x_test, pressure, previous_temperature_k=T_base + 5.0
    )

    assert abs(T_base - T_with_prev_lo) <= 1e-9, (
        f"previous偏低改变解: T_base={T_base}, T_prev_lo={T_with_prev_lo}"
    )
    assert abs(T_base - T_with_prev_hi) <= 1e-9, (
        f"previous偏高改变解: T_base={T_base}, T_prev_hi={T_with_prev_hi}"
    )
    assert abs(y_base - y_with_prev_lo) <= 1e-9
    assert abs(y_base - y_with_prev_hi) <= 1e-9

    # 提供极端 previous（区间端点附近），解仍必须一致
    T_with_prev_extreme, _ = bubble_point_temperature(
        x_test, pressure, previous_temperature_k=335.0
    )
    assert abs(T_base - T_with_prev_extreme) <= 1e-9, (
        f"极端 previous 改变解: T_base={T_base}, T_extreme={T_with_prev_extreme}"
    )


# ====================================================================
# 12. 非法输入抛 ValueError
# ====================================================================
def test_invalid_inputs_raise_value_error():
    """非法组成、非正压力、NaN/Inf 输入必须报 ValueError。"""
    # saturation_pressure_kpa
    with pytest.raises(ValueError):
        saturation_pressure_kpa("water", float("nan"))
    with pytest.raises(ValueError):
        saturation_pressure_kpa("water", -100.0)
    with pytest.raises(ValueError):
        saturation_pressure_kpa("water", float("inf"))
    with pytest.raises(ValueError):
        saturation_pressure_kpa("methanol", 350.0)  # 非法组分

    # nrtl_activity_coefficients
    with pytest.raises(ValueError):
        nrtl_activity_coefficients(-0.1, 350.0)  # x < 0
    with pytest.raises(ValueError):
        nrtl_activity_coefficients(1.1, 350.0)   # x > 1
    with pytest.raises(ValueError):
        nrtl_activity_coefficients(0.5, float("nan"))
    with pytest.raises(ValueError):
        nrtl_activity_coefficients(0.5, -100.0)  # T <= 0
    with pytest.raises(ValueError):
        nrtl_activity_coefficients(float("inf"), 350.0)

    # bubble_point_temperature
    with pytest.raises(ValueError):
        bubble_point_temperature(-0.1, 101.32)
    with pytest.raises(ValueError):
        bubble_point_temperature(1.1, 101.32)
    with pytest.raises(ValueError):
        bubble_point_temperature(0.5, 0.0)       # P <= 0
    with pytest.raises(ValueError):
        bubble_point_temperature(0.5, -100.0)
    with pytest.raises(ValueError):
        bubble_point_temperature(0.5, float("nan"))
    with pytest.raises(ValueError):
        bubble_point_temperature(float("nan"), 101.32)

    # 质量分数/摩尔分数转换
    with pytest.raises(ValueError):
        ethanol_mass_fraction_to_mole_fraction(-0.1)
    with pytest.raises(ValueError):
        ethanol_mass_fraction_to_mole_fraction(1.1)
    with pytest.raises(ValueError):
        ethanol_mass_fraction_to_mole_fraction(float("nan"))
    with pytest.raises(ValueError):
        ethanol_mole_fraction_to_mass_fraction(-0.1)
    with pytest.raises(ValueError):
        ethanol_mole_fraction_to_mass_fraction(1.1)
    with pytest.raises(ValueError):
        ethanol_mole_fraction_to_mass_fraction(float("inf"))
