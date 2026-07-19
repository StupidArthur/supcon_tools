"""
热力学后端模块。

阶段 A 只包含乙醇—水二元 VLE 计算（Antoine + NRTL）。
不注册为 BaseProgram，不是 DSL 节点，仅作为精馏塔模型的热力学计算后端。
"""

from components.thermo.ethanol_water import (
    MW_WATER_KG_PER_KMOL,
    MW_ETHANOL_KG_PER_KMOL,
    ANTOINE_WATER_KPA_C,
    ANTOINE_ETHANOL_KPA_C,
    NRTL_WATER_ETHANOL_A,
    NRTL_WATER_ETHANOL_B_K,
    NRTL_ETHANOL_WATER_A,
    NRTL_ETHANOL_WATER_B_K,
    NRTL_ALPHA,
    BUBBLE_POINT_T_MIN_K,
    BUBBLE_POINT_T_MAX_K,
    BUBBLE_POINT_MAX_ITERATIONS,
    BUBBLE_POINT_T_TOLERANCE_K,
    BUBBLE_POINT_P_TOLERANCE_KPA,
    saturation_pressure_kpa,
    nrtl_activity_coefficients,
    bubble_point_temperature,
    ethanol_mass_fraction_to_mole_fraction,
    ethanol_mole_fraction_to_mass_fraction,
)

__all__ = [
    "MW_WATER_KG_PER_KMOL",
    "MW_ETHANOL_KG_PER_KMOL",
    "ANTOINE_WATER_KPA_C",
    "ANTOINE_ETHANOL_KPA_C",
    "NRTL_WATER_ETHANOL_A",
    "NRTL_WATER_ETHANOL_B_K",
    "NRTL_ETHANOL_WATER_A",
    "NRTL_ETHANOL_WATER_B_K",
    "NRTL_ALPHA",
    "BUBBLE_POINT_T_MIN_K",
    "BUBBLE_POINT_T_MAX_K",
    "BUBBLE_POINT_MAX_ITERATIONS",
    "BUBBLE_POINT_T_TOLERANCE_K",
    "BUBBLE_POINT_P_TOLERANCE_KPA",
    "saturation_pressure_kpa",
    "nrtl_activity_coefficients",
    "bubble_point_temperature",
    "ethanol_mass_fraction_to_mole_fraction",
    "ethanol_mole_fraction_to_mass_fraction",
]
