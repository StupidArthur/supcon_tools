"""
常压乙醇—水连续精馏中试塔动态模型

阶段 C 实现范围（最终动态模型核心）：
- 12 块塔板 + 全凝器 + 回流罐 + 釜式再沸器
- 逐板总物料衡算 + 乙醇组分衡算 + 能量衡算
- 塔板温度由能量状态反算（不再用泡点代数）
- 塔压动态（气相存量 + 理想气体状态方程）
- 沿塔压降 ΔP_i = ΔP_dry + K_v · V_i²
- 再沸/冷凝负荷
- 显式 Heun/RK2 积分 + 子步
- 质量/乙醇/能量守恒诊断

阶段 C 暂不实现（后续阶段补）：
- 阀门动态、测量滞后、浓度分析仪（阶段 D）
- 稳态初始化文件持久化（阶段 D）
- 控制 DSL（阶段 E）
- 性能优化（阶段 G）

====================================================================
单位约定（与 spec §4.1 一致）
====================================================================

内部统一使用：
    物质量      kmol
    摩尔流量    kmol/s
    温度        K
    压力        kPa(a)
    组成        摩尔分数 0~1
    焓          kJ/kmol
    内能 U      kJ
    热负荷      kW（= kJ/s）
    热容        kJ/(kmol·K)
    体积        m³

对外位号按 spec §7 转换：
    流量        kg/h
    温度        ℃
    压力        kPa(a)
    产品浓度    质量分数 0~1
    塔板组成    摩尔分数 0~1
    液位        %

====================================================================
塔板编号（spec §5.2）
====================================================================

    1 号板 = 塔顶
    12 号板 = 塔底
    feed_stage = 7

数组索引 0..11 对应塔板 1..12（代码注释中会明确说明）。

====================================================================
阶段 C 关键模型关系
====================================================================

1. 能量衡算（spec §5.4）：
       dU_i/dt = L_{i-1}·h^L_{i-1} + V_{i+1}·h^V_{i+1} + F_i·h_F
                 - L_i·h^L_i - V_i·h^V_i - Q_{loss,i}

   其中 Q_{loss,i} = UA_i · (T_i - T_ambient)。

2. 塔板温度（spec §5.4，禁止仅用浓度查表）：
       T_i = T_ref + U_i / (M_i · Cp_L_mix(x_i))

   低压下液相内能 U ≈ 焓 H = M·h_L_mix。

3. 气相组成（VLE，归一化以兼容非平衡态）：
       y_raw_i = x_i · γ_i · P_i_sat(T_i) / P_i
       y_i = y_raw_i / Σ y_raw_i

4. 塔压动态（spec §5.6）：
       dN_v/dt = V_boil - V_condense - V_vent
       P_top = N_v · R · T_vapor_avg / V_gas

5. 沿塔压降（spec §5.6）：
       ΔP_i = ΔP_dry + K_v · V_i²
       P_i = P_top + Σ_{j< i} ΔP_j

6. 再沸器热负荷（spec §5.6，由 V_boil 反推）：
       Q_R = V_boil · ΔH_vap_mix(x_sump) + Q_loss_sump

7. 全凝器热负荷：
       V_condense = V_top（全凝器，所有进入蒸气均冷凝）
       Q_C = V_condense · ΔH_vap_mix(y_top)

8. CMO（恒摩尔流）假设：
   第一版采用 CMO 简化，V_i = V_boil 对所有塔板成立。CMO 在乙醇—水中
   误差约 5%（ΔH_vap_water/ΔH_vap_ethanol ≈ 1.05），可用于动态趋势和
   控制系统仿真。能量衡算仍逐板计算，用于报告能量守恒残差。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import numpy as np

from components.thermo.ethanol_water import (
    MW_WATER_KG_PER_KMOL,
    MW_ETHANOL_KG_PER_KMOL,
    T_REF_K,
    CP_LIQUID_WATER_KJ_PER_KMOL_K,
    CP_LIQUID_ETHANOL_KJ_PER_KMOL_K,
    CP_VAPOR_WATER_KJ_PER_KMOL_K,
    CP_VAPOR_ETHANOL_KJ_PER_KMOL_K,
    DH_VAP_WATER_KJ_PER_KMOL,
    DH_VAP_ETHANOL_KJ_PER_KMOL,
    T_BOIL_WATER_K,
    T_BOIL_ETHANOL_K,
    R_KJ_PER_KMOL_K,
    bubble_point_temperature,
    ethanol_mass_fraction_to_mole_fraction,
    ethanol_mole_fraction_to_mass_fraction,
    liquid_enthalpy_kj_per_kmol,
    vapor_enthalpy_kj_per_kmol,
    vapor_internal_energy_kj_per_kmol,
    temperature_from_vapor_internal_energy,
    heat_of_vaporization_kj_per_kmol,
    liquid_heat_capacity_kj_per_kmol_k,
    temperature_from_internal_energy,
    vapor_composition_at_state,
)
from components.utils.logger import get_logger
from controller.instance import InstanceRegistry
from .base import BaseProgram
from .ethanol_water_actuators import ValveActuator, ConcentrationAnalyzer

logger = get_logger(name="ethanol_water_distillation")


# ====================================================================
# 物理常数
# ====================================================================

#: 气体通用常数 (kPa·m³/(kmol·K))，用于理想气体状态方程 P = N·R·T/V
R_UNIVERSAL_KPA_M3_PER_KMOL_K: float = 8.314462618


# ====================================================================
# 辅助函数
# ====================================================================

def _mixture_molecular_weight(x_ethanol_mol: float) -> float:
    """
    二元乙醇—水混合液相平均分子量 (kg/kmol)。

    Args:
        x_ethanol_mol: 液相乙醇摩尔分数。

    Returns:
        平均分子量。
    """
    return x_ethanol_mol * MW_ETHANOL_KG_PER_KMOL + (1.0 - x_ethanol_mol) * MW_WATER_KG_PER_KMOL


def _kgmols_to_kgh(flow_kgmol_per_s: float, mw_kg_per_kmol: float) -> float:
    """kmol/s → kg/h。"""
    return flow_kgmol_per_s * mw_kg_per_kmol * 3600.0


def _kgh_to_kgmols(flow_kg_per_h: float, mw_kg_per_kmol: float) -> float:
    """kg/h → kmol/s。"""
    if mw_kg_per_kmol <= 0.0:
        return 0.0
    return flow_kg_per_h / (mw_kg_per_kmol * 3600.0)


def _compute_initial_valve_pct(
    target_flow: float,
    max_flow: float,
    characteristic: str,
    rangeability: float = 30.0,
) -> float:
    """
    根据目标流量反算阀门初始开度 (%)。

    使用归一化阀门特性（todo/5.md §4.1）：
        linear:             ratio = x                → x = ratio
        equal_percentage:   ratio = (R^x - 1)/(R-1)  → x = log(ratio*(R-1)+1)/log(R)

    其中 ratio = target_flow / max_flow ∈ [0, 1]。

    Args:
        target_flow: 目标流量（任意单位，与 max_flow 同单位）
        max_flow: 100% 开度下的最大流量（与 target_flow 同单位）
        characteristic: 'linear' 或 'equal_percentage'
        rangeability: 等百分比阀可调比

    Returns:
        初始开度 (0~100%)。0% 开度下流量严格为零（归一化等百分比）。
    """
    if max_flow <= 0.0:
        return 0.0
    if target_flow <= 0.0:
        return 0.0
    ratio = max(0.0, min(1.0, target_flow / max_flow))
    if characteristic == "linear":
        x = ratio
    else:
        # equal_percentage 归一化反函数
        x = math.log(ratio * (rangeability - 1.0) + 1.0) / math.log(rangeability)
    x = max(0.0, min(1.0, x))
    return x * 100.0


# ====================================================================
# 主模型类
# ====================================================================

class ETHANOL_WATER_DISTILLATION(BaseProgram):
    """
    常压乙醇—水连续精馏中试塔（阶段 C）。

    阶段 C 实现：
    - 12 块塔板逐板物料 + 乙醇组分 + 能量衡算
    - 全凝器 + 回流罐 + 釜式再沸器（平衡级）
    - 塔板温度由能量状态反算
    - 塔压动态（气相存量 + 理想气体状态方程）
    - 沿塔压降 ΔP = ΔP_dry + K_v·V²
    - 再沸/冷凝负荷
    - Heun/RK2 积分 + 子步
    - 质量/乙醇/能量守恒诊断

    不实现：
    - 阀门动态、测量滞后（阶段 D）
    - 控制 DSL（阶段 E）
    """

    # 文档属性
    name = "ethanol_water_distillation"
    chinese_name = "乙醇水连续精馏塔"
    doc = """
# 乙醇水连续精馏塔（阶段 C）

常压乙醇—水连续溶剂回收中试塔动态模型。

## 阶段 C 实现范围

- 12 块塔板 + 全凝器 + 回流罐 + 釜式再沸器
- 逐板总物料 + 乙醇组分 + 能量衡算
- 塔板温度由能量状态反算（不再用泡点代数）
- 塔压动态（气相存量 + 理想气体状态方程）
- 沿塔压降 ΔP = ΔP_dry + K_v·V²
- 再沸/冷凝负荷
- 显式 Heun/RK2 积分 + 子步

## 塔板编号

1 号板 = 塔顶，12 号板 = 塔底，进料板 = 第 7 块。
"""

    # 固定结构参数
    TRAY_COUNT: int = 12
    FEED_STAGE: int = 7  # 1-indexed

    default_params: Dict[str, Any] = {
        # 塔结构
        "tray_count": 12,
        "feed_stage": 7,
        # 压力（初始/设定，阶段 C 实现动态）
        "top_pressure_kpa": 101.325,
        "pressure_drop_per_stage_kpa": 0.3,    # ΔP_dry（CMO 下等于总 ΔP）
        "pressure_drop_kv_kpa_s2_per_kgmol2": 0.0,  # ΔP 中 V² 项系数
        # 标称持液量 (kmol)
        "m_tray_nom_kmol": 0.15,
        "m_drum_nom_kmol": 0.5,
        "m_sump_nom_kmol": 1.5,
        # 回流罐与塔釜最大容积 (kmol)
        "m_drum_max_kmol": 1.0,
        "m_sump_max_kmol": 3.0,
        # 稳态流量初值 (kmol/s)，参考工况 100 kg/h 进料
        "feed_flow_kgmol_per_s": 0.001307,    # 100 kg/h
        "distillate_flow_kgmol_per_s": 0.000209,
        "bottoms_flow_kgmol_per_s": 0.001098,
        "reflux_flow_kgmol_per_s": 0.000625,
        "vapor_boilup_kgmol_per_s": 0.000834,
        # 进料
        "feed_ethanol_wt": 0.25,
        "feed_temperature_c": 60.0,
        # 阶段 C 新增：气相与散热参数
        "vapor_volume_m3": 0.35,                # 塔内气相总体积 (m³)
        "tray_ua_kw_per_k": 0.005,              # 单板散热 UA (kW/K)
        "drum_ua_kw_per_k": 0.01,               # 回流罐散热 UA (kW/K)
        "sump_ua_kw_per_k": 0.02,               # 塔釜散热 UA (kW/K)
        "ambient_temperature_c": 25.0,          # 环境温度 (℃)
        # 数值积分
        "max_internal_step": 0.05,
        # 初始化
        "initialization_mode": "STEADY",
        "random_seed": 20260719,
        # ===== 阶段 D 新增：阀门动态（spec §6.2） =====
        # 每个阀门：(满行程时间 s, 特性)
        "feed_valve_full_travel_s": 10.0,
        "feed_valve_characteristic": "equal_percentage",
        "reflux_valve_full_travel_s": 10.0,
        "reflux_valve_characteristic": "equal_percentage",
        "distillate_valve_full_travel_s": 12.0,
        "distillate_valve_characteristic": "linear",
        "bottoms_valve_full_travel_s": 12.0,
        "bottoms_valve_characteristic": "linear",
        "steam_valve_full_travel_s": 15.0,
        "steam_valve_characteristic": "equal_percentage",
        "cooling_valve_full_travel_s": 15.0,
        "cooling_valve_characteristic": "equal_percentage",
        # 阀门可调比（等百分比阀参数）
        "valve_rangeability": 30.0,
        # ===== 阶段 1 新增：阀门额定质量流量（todo/5.md §4.2） =====
        # 四个过程阀的额定流量按 kg/h 给出（DCS 单位），运行时根据流股组成换算为 kmol/s。
        # 蒸汽和冷却水是公用工程，保持 kg/h 不转换为 kmol/s。
        # 额定值按参考工况（spec §2.3）×1.5 设计余量。
        "feed_valve_max_flow_kg_per_h": 150.0,        # 参考进料 100 kg/h × 1.5
        "reflux_valve_max_flow_kg_per_h": 150.0,      # 参考回流 84 kg/h × 1.5 ≈ 126，圆整到 150
        "distillate_valve_max_flow_kg_per_h": 50.0,   # 参考塔顶 28 kg/h × 1.5 ≈ 42，圆整到 50
        "bottoms_valve_max_flow_kg_per_h": 120.0,     # 参考塔底 72 kg/h × 1.5 ≈ 108，圆整到 120
        "steam_valve_max_flow_kg_per_h": 100.0,       # 公用工程蒸汽（DCS 可测）
        "cooling_valve_max_flow_kg_per_h": 7000.0,    # 公用工程冷却水（DCS 可测）
        # ===== 阶段 1 新增：公用工程参数（todo/5.md §3.2） =====
        # 注意：阶段 1 仅发布位号和输入接口，不接入再沸/冷凝机理。
        # Q_R → V_boil、Q_C → V_condense、压力动态属于阶段 2。
        "cooling_water_temperature_c": 25.0,           # 冷却水供入温度 (℃)
        "steam_supply_pressure_kpa": 300.0 + 101.325,  # 蒸汽供入压力 kPa(a)（300 kPa(g)）
        # ===== 阶段 2 新增：再沸/冷凝机理参数（todo/5.md §3.2、§5、§6） =====
        # 蒸汽侧（spec §5.1）
        "steam_latent_heat_kj_per_kg": 2133.0,         # 蒸汽汽化潜热 (kJ/kg)
        "steam_heat_transfer_efficiency": 0.95,         # 蒸汽侧传热效率
        # 冷却侧（spec §6.3）
        "cooling_water_cp_kj_per_kg_k": 4.18,           # 冷却水比热 (kJ/(kg·K))
        "cooling_water_design_delta_t_k": 8.0,          # 冷却水设计温差 (K)
        "condenser_ua_kw_per_k": 1.2,                   # 冷凝器 UA (kW/K)
        # 压力下限和动态时间常数（spec §6.4、§5.2）
        "p_vapor_floor_kpa": 70.0,                      # 气相库存下限对应压力 (kPa)
        "tau_condenser_inventory_s": 5.0,               # 气相库存释放时间常数 (s)
        "tau_sump_heat_s": 30.0,                        # 塔釜显热时间常数 (s)
        "tau_phase_s": 2.0,                             # 塔釜相变时间常数 (s)
        # 放空（第一版关闭，spec §6.5）
        "vent_flow_kgmol_per_s": 0.0,
        # ===== 阶段 1 兼容字段（仅用于 deprecated get_flow_kgmol_per_s()，将在阶段 2 删除） =====
        # 注意：正式模型不使用这些字段，应使用上面的 *_valve_max_flow_kg_per_h。
        "feed_valve_max_flow_kgmol_per_s": 0.001961,
        "reflux_valve_max_flow_kgmol_per_s": 0.000938,
        "distillate_valve_max_flow_kgmol_per_s": 0.000314,
        "bottoms_valve_max_flow_kgmol_per_s": 0.001647,
        "steam_valve_max_flow_kgmol_per_s": 0.001251,
        "cooling_valve_max_flow_kgmol_per_s": 0.001251,
        # ===== 阶段 D 新增：浓度分析仪（spec §6.3） =====
        "analyzer_tau_lag_s": 30.0,         # 一阶滞后时间常数
        "analyzer_sample_interval_s": 5.0,  # 采样间隔
        "analyzer_transport_delay_s": 60.0, # 传输延迟
        "analyzer_noise_std": 0.005,        # 高斯噪声标准差（质量分数）
        "analyzer_drift_rate_per_s": 0.0,   # 零点漂移率（per second）
        # 基础测量短滞后（spec §6.3：温度、压力、流量用短一阶滞后）
        "basic_measurement_lag_s": 2.0,
        # ===== 阶段 D 新增：参考稳态文件 =====
        # 阶段 4.1（todo/5.md §9.1）：删除 auto_save_reference_state，
        # 参考状态只能由显式离线工具 tools/generate_ethanol_water_reference_state.py 生成。
        "reference_state_file": "components/programs/data/ethanol_water_reference_state.json",
    }

    stored_attributes = [
        # 塔顶塔底
        "top_pressure_kpa",
        "bottom_pressure_kpa",
        "top_temperature_c",
        "bottom_temperature_c",
        # 流量
        "feed_flow_kg_h",
        "reflux_flow_kg_h",
        "distillate_flow_kg_h",
        "bottoms_flow_kg_h",
        "vapor_boilup_kg_h",
        # 阶段 1 新增：公用工程质量流量（todo/5.md §4.3）
        # 注意：阶段 1 仅发布位号，不接入再沸/冷凝机理（阶段 2）
        "steam_flow_kg_h",
        "cooling_flow_kg_h",
        # 阶段 1 新增：公用工程状态（todo/5.md §3.2）
        "cooling_water_temperature_c",
        "steam_supply_pressure_kpa",
        # 液位
        "reflux_drum_level_pct",
        "reboiler_level_pct",
        # 组成（真实值）
        "top_ethanol_x",
        "bottom_ethanol_x",
        "top_ethanol_wt",
        "bottom_ethanol_wt",
        # 阶段 C 新增：能量与压力
        "reboiler_duty_kw",
        "condenser_duty_kw",
        "energy_balance_residual_kw",
        "vapor_holdup_kgmol",
        "ambient_temperature_c",
        # 守恒诊断
        "mass_balance_residual_kg_h",
        "ethanol_balance_residual_kg_h",
        # 阶段 3.2 新增：明确闭合残差位号（todo/5.md §11 + 阶段 3.2 修正）
        # 兼容位号 mass_balance_residual_kg_h / ethanol_balance_residual_kg_h
        # / energy_balance_residual_kw 继续指向对应 closure residual
        "mass_closure_residual_kg_h",
        "ethanol_closure_residual_kg_h",
        "energy_closure_residual_kw",
        # 阶段 2 新增：瞬时积累率（区分 accumulation 和 closure residual）
        "mass_accumulation_kg_h",
        "ethanol_accumulation_kg_h",
        "energy_accumulation_kw",
        # 阶段 D 新增：六个阀门（spec §6.2 实际开度和流量必须对外暴露）
        "feed_valve_command_pct", "feed_valve_actual_pct",
        "reflux_valve_command_pct", "reflux_valve_actual_pct",
        "distillate_valve_command_pct", "distillate_valve_actual_pct",
        "bottoms_valve_command_pct", "bottoms_valve_actual_pct",
        "steam_valve_command_pct", "steam_valve_actual_pct",
        "cooling_valve_command_pct", "cooling_valve_actual_pct",
        # 阶段 D 新增：分析仪（spec §6.3 真实值和仪表值分开）
        "top_ethanol_wt_true", "top_ethanol_analyzer",
        "bottom_ethanol_wt_true", "bottom_ethanol_analyzer",
        # 12 块塔板固定展开
        "stage_01_temperature_c", "stage_02_temperature_c", "stage_03_temperature_c",
        "stage_04_temperature_c", "stage_05_temperature_c", "stage_06_temperature_c",
        "stage_07_temperature_c", "stage_08_temperature_c", "stage_09_temperature_c",
        "stage_10_temperature_c", "stage_11_temperature_c", "stage_12_temperature_c",
        "stage_01_ethanol_x", "stage_02_ethanol_x", "stage_03_ethanol_x",
        "stage_04_ethanol_x", "stage_05_ethanol_x", "stage_06_ethanol_x",
        "stage_07_ethanol_x", "stage_08_ethanol_x", "stage_09_ethanol_x",
        "stage_10_ethanol_x", "stage_11_ethanol_x", "stage_12_ethanol_x",
        "stage_01_liquid_holdup_kg", "stage_02_liquid_holdup_kg", "stage_03_liquid_holdup_kg",
        "stage_04_liquid_holdup_kg", "stage_05_liquid_holdup_kg", "stage_06_liquid_holdup_kg",
        "stage_07_liquid_holdup_kg", "stage_08_liquid_holdup_kg", "stage_09_liquid_holdup_kg",
        "stage_10_liquid_holdup_kg", "stage_11_liquid_holdup_kg", "stage_12_liquid_holdup_kg",
        # ===== 阶段 2 新增位号（todo/5.md §7.2、§11） =====
        # 实际冷凝量、内部 V_boil（避免与外部输入冲突）
        "vapor_condense_kgmol_per_s",
        "vapor_boilup_kgmol_per_s_internal",
        # KPI 位号
        "ethanol_recovery_pct",
        "qualified_product_flow_kg_h",
        "specific_steam_kg_per_kg_product",
        # 原始液位（未钳制）
        "raw_reflux_drum_level_pct",
        "raw_reboiler_level_pct",
        # 气相状态位号（spec §6.1）
        "vapor_ethanol_y",
        "vapor_temperature_c",
        # 守恒积累率位号（spec §11）
        "mass_accumulation_kg_h",
        "ethanol_accumulation_kg_h",
        "energy_accumulation_kw",
    ]

    input_schema = [
        {"name": "feed_flow_kgmol_per_s", "type": "float", "connectable": True, "desc": "进料摩尔流量(kmol/s)（直接流量模式）"},
        {"name": "reflux_flow_kgmol_per_s", "type": "float", "connectable": True, "desc": "回流量(kmol/s)（直接流量模式）"},
        {"name": "distillate_flow_kgmol_per_s", "type": "float", "connectable": True, "desc": "塔顶采出(kmol/s)（直接流量模式）"},
        {"name": "bottoms_flow_kgmol_per_s", "type": "float", "connectable": True, "desc": "塔底采出(kmol/s)（直接流量模式）"},
        {"name": "vapor_boilup_kgmol_per_s", "type": "float", "connectable": True, "desc": "再沸蒸气量(kmol/s)（直接流量模式）"},
        {"name": "feed_ethanol_wt", "type": "float", "connectable": True, "desc": "进料乙醇质量分数"},
        {"name": "feed_temperature_c", "type": "float", "connectable": True, "desc": "进料温度(℃)"},
        {"name": "ambient_temperature_c", "type": "float", "connectable": True, "desc": "环境温度(℃)"},
        # 阶段 D 新增：阀位输入（spec §6.1，0~100%）
        {"name": "feed_valve_pct", "type": "float", "connectable": True, "desc": "进料阀命令开度(%)"},
        {"name": "reflux_valve_pct", "type": "float", "connectable": True, "desc": "回流阀命令开度(%)"},
        {"name": "distillate_valve_pct", "type": "float", "connectable": True, "desc": "塔顶采出阀命令开度(%)"},
        {"name": "bottoms_valve_pct", "type": "float", "connectable": True, "desc": "塔底采出阀命令开度(%)"},
        {"name": "steam_valve_pct", "type": "float", "connectable": True, "desc": "蒸汽阀命令开度(%)"},
        {"name": "cooling_valve_pct", "type": "float", "connectable": True, "desc": "冷却水阀命令开度(%)"},
        # 阶段 1 新增：公用工程输入（todo/5.md §3.2、§6.1）
        # 注意：阶段 1 仅接受输入并发布位号，不影响再沸/冷凝/压力动态（阶段 2 接入）
        {"name": "cooling_water_temperature_c", "type": "float", "connectable": True, "desc": "冷却水供入温度(℃)"},
        {"name": "steam_supply_pressure_kpa", "type": "float", "connectable": True, "desc": "蒸汽供入压力(kPa(a))"},
    ]

    param_descriptions: Dict[str, str] = {
        "top_pressure_kpa": "塔顶压力(kPa(a))",
        "bottom_pressure_kpa": "塔底压力(kPa(a))",
        "top_temperature_c": "塔顶温度(℃)",
        "bottom_temperature_c": "塔底温度(℃)",
        "feed_flow_kg_h": "进料流量(kg/h)",
        "reflux_flow_kg_h": "回流量(kg/h)",
        "distillate_flow_kg_h": "塔顶采出(kg/h)",
        "bottoms_flow_kg_h": "塔底采出(kg/h)",
        "vapor_boilup_kg_h": "再沸蒸气量(kg/h)",
        "reflux_drum_level_pct": "回流罐液位(%)",
        "reboiler_level_pct": "塔釜液位(%)",
        "top_ethanol_x": "塔顶乙醇摩尔分数",
        "bottom_ethanol_x": "塔底乙醇摩尔分数",
        "top_ethanol_wt": "塔顶乙醇质量分数",
        "bottom_ethanol_wt": "塔底乙醇质量分数",
        "reboiler_duty_kw": "再沸器热负荷(kW)",
        "condenser_duty_kw": "冷凝器热负荷(kW)",
        "energy_balance_residual_kw": "能量守恒残差(kW)",
        "vapor_holdup_kgmol": "塔内气相总存量(kmol)",
        "ambient_temperature_c": "环境温度(℃)",
        "mass_balance_residual_kg_h": "总质量守恒残差(kg/h)",
        "ethanol_balance_residual_kg_h": "乙醇守恒残差(kg/h)",
        # 阶段 D 新增位号
        "feed_valve_command_pct": "进料阀命令开度(%)",
        "feed_valve_actual_pct": "进料阀实际开度(%)",
        "reflux_valve_command_pct": "回流阀命令开度(%)",
        "reflux_valve_actual_pct": "回流阀实际开度(%)",
        "distillate_valve_command_pct": "塔顶采出阀命令开度(%)",
        "distillate_valve_actual_pct": "塔顶采出阀实际开度(%)",
        "bottoms_valve_command_pct": "塔底采出阀命令开度(%)",
        "bottoms_valve_actual_pct": "塔底采出阀实际开度(%)",
        "steam_valve_command_pct": "蒸汽阀命令开度(%)",
        "steam_valve_actual_pct": "蒸汽阀实际开度(%)",
        "cooling_valve_command_pct": "冷却水阀命令开度(%)",
        "cooling_valve_actual_pct": "冷却水阀实际开度(%)",
        "top_ethanol_wt_true": "塔顶乙醇质量分数真实值",
        "top_ethanol_analyzer": "塔顶乙醇分析仪读数",
        "bottom_ethanol_wt_true": "塔底乙醇质量分数真实值",
        "bottom_ethanol_analyzer": "塔底乙醇分析仪读数",
        # 阶段 1 新增：公用工程位号（todo/5.md §4.3）
        "steam_flow_kg_h": "公用工程蒸汽质量流量(kg/h)",
        "cooling_flow_kg_h": "公用工程冷却水质量流量(kg/h)",
        "cooling_water_temperature_c": "冷却水供入温度(℃)",
        "steam_supply_pressure_kpa": "蒸汽供入压力(kPa(a))",
    }

    def __init__(self, cycle_time: float, **kwargs: Any) -> None:
        """
        初始化精馏塔模型。

        Args:
            cycle_time: 控制器周期（秒）。
            **kwargs: 其他参数，覆盖 default_params。
        """
        super().__init__(cycle_time, **kwargs)

        self._validate_configuration()

        # 塔板数固定为 12（spec §2.2）
        self._n_trays = int(self.TRAY_COUNT)
        self._feed_stage_idx = int(self.FEED_STAGE) - 1  # 0-indexed

        # 压力参数
        self._p_top_setpoint_kpa = float(self.top_pressure_kpa)
        self._pressure_drop_dry_kpa = float(self.pressure_drop_per_stage_kpa)
        self._pressure_drop_kv = float(self.pressure_drop_kv_kpa_s2_per_kgmol2)

        # 标称持液量
        self._m_tray_nom = float(self.m_tray_nom_kmol)
        self._m_drum_nom = float(self.m_drum_nom_kmol)
        self._m_sump_nom = float(self.m_sump_nom_kmol)
        self._m_drum_max = float(self.m_drum_max_kmol)
        self._m_sump_max = float(self.m_sump_max_kmol)

        # 阶段 C 散热与气相参数
        self._vapor_volume_m3 = float(self.vapor_volume_m3)
        self._tray_ua = float(self.tray_ua_kw_per_k)
        self._drum_ua = float(self.drum_ua_kw_per_k)
        self._sump_ua = float(self.sump_ua_kw_per_k)
        self._ambient_temperature_k = float(self.ambient_temperature_c) + 273.15

        # 初始化状态
        self._load_or_build_initial_state()

        # 数值积分参数
        self._max_internal_step = float(self.max_internal_step)
        self._substeps = max(1, int(math.ceil(self.cycle_time / self._max_internal_step)))
        self._internal_dt = self.cycle_time / self._substeps

        # 上一周期外部流量输入（用于守恒诊断和首次 execute 时的默认值）
        self._feed_flow_kgmol_per_s = float(self.feed_flow_kgmol_per_s)
        self._reflux_flow_kgmol_per_s = float(self.reflux_flow_kgmol_per_s)
        self._distillate_flow_kgmol_per_s = float(self.distillate_flow_kgmol_per_s)
        self._bottoms_flow_kgmol_per_s = float(self.bottoms_flow_kgmol_per_s)
        self._vapor_boilup_kgmol_per_s = float(self.vapor_boilup_kgmol_per_s)
        self._feed_ethanol_wt = float(self.feed_ethanol_wt)
        self._feed_temperature_c = float(self.feed_temperature_c)

        # 阶段 1 修正：六个阀门的额定质量流量（todo/5.md §4.2）
        # 过程阀（feed/reflux/distillate/bottoms）：质量流量 → 运行时按流股组成换算 kmol/s
        # 公用工程阀（steam/cooling）：保持 kg/h，不转 kmol/s
        self._valve_max_flow_kg_per_h: Dict[str, float] = {
            "feed":       float(self.feed_valve_max_flow_kg_per_h),
            "reflux":     float(self.reflux_valve_max_flow_kg_per_h),
            "distillate": float(self.distillate_valve_max_flow_kg_per_h),
            "bottoms":    float(self.bottoms_valve_max_flow_kg_per_h),
            "steam":      float(self.steam_valve_max_flow_kg_per_h),
            "cooling":    float(self.cooling_valve_max_flow_kg_per_h),
        }

        # 阶段 1.1 修正：稳态初始质量流量（kg/h），用于反算阀门初始开度
        # 过程阀：kmol/s × 流股平均分子量 × 3600 = kg/h
        # steam/cooling：阶段 2 真实参考工况质量流量
        # 关键：不能依赖尚未发布的 top_ethanol_wt/bottom_ethanol_wt/bottom_ethanol_x
        #       应直接从已创建的内部状态求初始摩尔分数
        feed_mw_init = _mixture_molecular_weight(
            ethanol_mass_fraction_to_mole_fraction(self._feed_ethanol_wt)
        )
        # 阶段 1.1 修正：回流/塔顶采出使用回流罐组成（塔顶组成）
        x_drum_init = self._nE_drum / self._M_drum
        reflux_mw_init = _mixture_molecular_weight(x_drum_init)
        distillate_mw_init = reflux_mw_init  # 塔顶采出与回流同组成
        # 阶段 1.1 修正：塔底采出使用塔釜组成
        x_sump_init = self._nE_sump / self._M_sump
        bottoms_mw_init = _mixture_molecular_weight(x_sump_init)
        # 阶段 2 真实参考蒸汽流量（todo/5.md §3.2、§5.1）
        # 由 Q_R_available = (ṁ_steam/3600) * ΔH_steam * η_R 反推
        # 假设稳态下 Q_R_available ≈ V_boil * ΔH_vap_sump（忽略 Q_loss 和显热项）
        # ṁ_steam ≈ V_boil * ΔH_vap_sump * 3600 / (ΔH_steam * η_R)
        dh_vap_sump_init = max(heat_of_vaporization_kj_per_kmol(x_sump_init), 1.0)
        # 注意：此处 _steam_latent_heat_kj_per_kg 尚未缓存，使用公共属性
        # （BaseProgram 在 __init__ 体执行前已从 default_params 设置公共属性）
        steam_mass_flow_init_kg_h = (
            self._vapor_boilup_kgmol_per_s
            * dh_vap_sump_init
            * 3600.0
            / (float(self.steam_latent_heat_kj_per_kg) * float(self.steam_heat_transfer_efficiency))
        )
        steady_mass_flow_kg_per_h: Dict[str, float] = {
            "feed":       _kgmols_to_kgh(self._feed_flow_kgmol_per_s, feed_mw_init),
            "reflux":     _kgmols_to_kgh(self._reflux_flow_kgmol_per_s, reflux_mw_init),
            "distillate": _kgmols_to_kgh(self._distillate_flow_kgmol_per_s, distillate_mw_init),
            "bottoms":    _kgmols_to_kgh(self._bottoms_flow_kgmol_per_s, bottoms_mw_init),
            # 阶段 2：蒸汽质量流量由 Q_R 反推（参考工况 ≈ 60.47 kg/h）
            "steam":      steam_mass_flow_init_kg_h,
            # 冷却水：参考工况下约 3500 kg/h（与冷凝负荷匹配），初始按 50% 开度对应值
            "cooling":    self._valve_max_flow_kg_per_h["cooling"] * 0.5,
        }

        # 阶段 D：创建六个阀门（spec §6.2）
        # 阶段 1 修正：ValveActuator 不再绑定 kmol/s，初始开度按质量流量反算
        rangeability = float(self.valve_rangeability)
        self._valves: Dict[str, ValveActuator] = {
            key: ValveActuator(
                name=f"{key}_valve",
                full_travel_time_s=float(getattr(self, f"{key}_valve_full_travel_s")),
                characteristic=str(getattr(self, f"{key}_valve_characteristic")),  # type: ignore[arg-type]
                initial_command_pct=_compute_initial_valve_pct(
                    steady_mass_flow_kg_per_h[key],
                    self._valve_max_flow_kg_per_h[key],
                    str(getattr(self, f"{key}_valve_characteristic")),
                    rangeability,
                ),
                rangeability=rangeability,
            )
            for key in ("feed", "reflux", "distillate", "bottoms", "steam", "cooling")
        }

        # 阶段 1 新增：公用工程状态（todo/5.md §3.2）
        # 注意：阶段 1 仅持有状态和发布位号，不影响再沸/冷凝/压力动态（阶段 2 接入）
        self._cooling_water_temperature_c = float(self.cooling_water_temperature_c)
        self._steam_supply_pressure_kpa = float(self.steam_supply_pressure_kpa)

        # ===== 阶段 2 新增：再沸/冷凝/气相库存参数（todo/5.md §3.2、§5、§6） =====
        self._steam_latent_heat_kj_per_kg = float(self.steam_latent_heat_kj_per_kg)
        self._steam_heat_transfer_efficiency = float(self.steam_heat_transfer_efficiency)
        self._cooling_water_cp_kj_per_kg_k = float(self.cooling_water_cp_kj_per_kg_k)
        self._cooling_water_design_delta_t_k = float(self.cooling_water_design_delta_t_k)
        self._condenser_ua_kw_per_k = float(self.condenser_ua_kw_per_k)
        self._p_vapor_floor_kpa = float(self.p_vapor_floor_kpa)
        self._tau_condenser_inventory_s = float(self.tau_condenser_inventory_s)
        self._tau_sump_heat_s = float(self.tau_sump_heat_s)
        self._tau_phase_s = float(self.tau_phase_s)
        self._vent_flow_kgmol_per_s = float(self.vent_flow_kgmol_per_s)

        # 阶段 1 新增：上一周期公用工程质量流量（kg/h），用于在非阀位模式下保持连续性
        self._last_steam_flow_kg_per_h = steady_mass_flow_kg_per_h["steam"]
        self._last_cooling_flow_kg_per_h = steady_mass_flow_kg_per_h["cooling"]

        # 阶段 D：创建两个浓度分析仪（spec §6.3）
        # 初始真实值用稳态浓度（init 已完成）
        seed = int(self.random_seed)
        top_wt_init = float(self.top_ethanol_wt) if hasattr(self, "top_ethanol_wt") else 0.85
        bottom_wt_init = float(self.bottom_ethanol_wt) if hasattr(self, "bottom_ethanol_wt") else 0.015
        self._analyzers: Dict[str, ConcentrationAnalyzer] = {
            "top": ConcentrationAnalyzer(
                name="top_analyzer",
                tau_lag_s=float(self.analyzer_tau_lag_s),
                sample_interval_s=float(self.analyzer_sample_interval_s),
                transport_delay_s=float(self.analyzer_transport_delay_s),
                noise_std=float(self.analyzer_noise_std),
                drift_rate_per_s=float(self.analyzer_drift_rate_per_s),
                random_seed=seed,
                initial_true_value=top_wt_init,
                initial_measured_value=top_wt_init,
            ),
            "bottom": ConcentrationAnalyzer(
                name="bottom_analyzer",
                tau_lag_s=float(self.analyzer_tau_lag_s),
                sample_interval_s=float(self.analyzer_sample_interval_s),
                transport_delay_s=float(self.analyzer_transport_delay_s),
                noise_std=float(self.analyzer_noise_std),
                drift_rate_per_s=float(self.analyzer_drift_rate_per_s),
                random_seed=seed + 1,  # 不同种子避免噪声相关性
                initial_true_value=bottom_wt_init,
                initial_measured_value=bottom_wt_init,
            ),
        }

        # 阶段 D：执行机构模式标志
        # True = 阀位模式（阀位输入驱动流量），False = 直接流量模式（向后兼容阶段 B/C）
        self._valve_mode_enabled = False

        # 阶段 D：参考稳态文件路径和加载状态
        self._reference_state_path: Optional[str] = None
        self._reference_state_loaded = False
        self._reference_state_saved = False

        # 阶段 D：快照关键设备参数（用于参数哈希）
        # spec §10.1: 用户修改关键设备参数后，旧稳态不得静默复用。
        # 注意：top_pressure_kpa 等部分参数在运行时会被 _publish_scalar_attributes
        # 覆盖为动态值，所以必须用 __init__ 时的快照来计算哈希。
        self._params_hash_snapshot: Dict[str, Any] = {
            key: getattr(self, key) for key in self._PARAMS_HASH_KEYS
        }

        # 对外位号初值
        self._publish_scalar_attributes()

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------
    def _validate_configuration(self) -> None:
        """构造时参数校验，失败抛 ValueError。"""
        if not math.isfinite(self.cycle_time) or self.cycle_time <= 0.0:
            raise ValueError(f"cycle_time 必须大于0，实际值={self.cycle_time!r}")

        if int(self.TRAY_COUNT) != 12:
            raise ValueError(f"TRAY_COUNT 第一版固定为 12，实际值={self.TRAY_COUNT}")

        if int(self.FEED_STAGE) < 1 or int(self.FEED_STAGE) > 12:
            raise ValueError(f"FEED_STAGE 必须位于 [1, 12]，实际值={self.FEED_STAGE}")

        for name in (
            "top_pressure_kpa", "pressure_drop_per_stage_kpa",
            "pressure_drop_kv_kpa_s2_per_kgmol2",
            "m_tray_nom_kmol", "m_drum_nom_kmol", "m_sump_nom_kmol",
            "m_drum_max_kmol", "m_sump_max_kmol",
            "feed_flow_kgmol_per_s", "distillate_flow_kgmol_per_s",
            "bottoms_flow_kgmol_per_s", "reflux_flow_kgmol_per_s",
            "vapor_boilup_kgmol_per_s",
            "feed_ethanol_wt", "feed_temperature_c",
            "vapor_volume_m3", "tray_ua_kw_per_k", "drum_ua_kw_per_k",
            "sump_ua_kw_per_k", "ambient_temperature_c",
            "max_internal_step",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"参数无效: {name} 必须为有限数值，实际值={value!r}")

        if float(self.top_pressure_kpa) <= 0.0:
            raise ValueError(f"top_pressure_kpa 必须大于0，实际值={self.top_pressure_kpa!r}")

        if float(self.pressure_drop_per_stage_kpa) < 0.0:
            raise ValueError(
                f"pressure_drop_per_stage_kpa 不得为负，实际值={self.pressure_drop_per_stage_kpa!r}"
            )

        if float(self.pressure_drop_kv_kpa_s2_per_kgmol2) < 0.0:
            raise ValueError(
                f"pressure_drop_kv_kpa_s2_per_kgmol2 不得为负，实际值="
                f"{self.pressure_drop_kv_kpa_s2_per_kgmol2!r}"
            )

        if float(self.m_tray_nom_kmol) <= 0.0:
            raise ValueError(f"m_tray_nom_kmol 必须大于0，实际值={self.m_tray_nom_kmol!r}")
        if float(self.m_drum_nom_kmol) <= 0.0:
            raise ValueError(f"m_drum_nom_kmol 必须大于0，实际值={self.m_drum_nom_kmol!r}")
        if float(self.m_sump_nom_kmol) <= 0.0:
            raise ValueError(f"m_sump_nom_kmol 必须大于0，实际值={self.m_sump_nom_kmol!r}")
        if float(self.m_drum_max_kmol) <= float(self.m_drum_nom_kmol):
            raise ValueError("m_drum_max_kmol 必须大于 m_drum_nom_kmol")
        if float(self.m_sump_max_kmol) <= float(self.m_sump_nom_kmol):
            raise ValueError("m_sump_max_kmol 必须大于 m_sump_nom_kmol")

        if not (0.0 <= float(self.feed_ethanol_wt) <= 1.0):
            raise ValueError(
                f"feed_ethanol_wt 必须位于 [0, 1]，实际值={self.feed_ethanol_wt!r}"
            )

        if float(self.vapor_volume_m3) <= 0.0:
            raise ValueError(f"vapor_volume_m3 必须大于0，实际值={self.vapor_volume_m3!r}")

        if float(self.tray_ua_kw_per_k) < 0.0 or float(self.drum_ua_kw_per_k) < 0.0 \
                or float(self.sump_ua_kw_per_k) < 0.0:
            raise ValueError("UA 参数不得为负")

        if float(self.max_internal_step) <= 0.0 or float(self.max_internal_step) > self.cycle_time:
            raise ValueError(
                f"max_internal_step 必须位于 (0, cycle_time]，实际值={self.max_internal_step!r}"
            )

        # ===== 阶段 1.1 新增：六个阀门额定质量流量校验（todo/5.md §4.2） =====
        # 必须是有限数，并且严格大于零
        for name in (
            "feed_valve_max_flow_kg_per_h",
            "reflux_valve_max_flow_kg_per_h",
            "distillate_valve_max_flow_kg_per_h",
            "bottoms_valve_max_flow_kg_per_h",
            "steam_valve_max_flow_kg_per_h",
            "cooling_valve_max_flow_kg_per_h",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"参数无效: {name} 必须为有限数值，实际值={value!r}")
            if float(value) <= 0.0:
                raise ValueError(f"{name} 必须严格大于0，实际值={value!r}")

        # ===== 阶段 1.1 新增：公用工程参数校验（todo/5.md §3.2） =====
        # cooling_water_temperature_c：有限数且高于绝对零度（-273.15 ℃）
        cwt = self.cooling_water_temperature_c
        if not isinstance(cwt, (int, float)) or not math.isfinite(float(cwt)):
            raise ValueError(f"参数无效: cooling_water_temperature_c 必须为有限数值，实际值={cwt!r}")
        if float(cwt) <= -273.15:
            raise ValueError(
                f"cooling_water_temperature_c 必须高于绝对零度 (-273.15 ℃)，实际值={cwt!r}"
            )
        # steam_supply_pressure_kpa：有限数且作为绝压严格大于零
        ssp = self.steam_supply_pressure_kpa
        if not isinstance(ssp, (int, float)) or not math.isfinite(float(ssp)):
            raise ValueError(f"参数无效: steam_supply_pressure_kpa 必须为有限数值，实际值={ssp!r}")
        if float(ssp) <= 0.0:
            raise ValueError(
                f"steam_supply_pressure_kpa 作为绝压必须严格大于0，实际值={ssp!r}"
            )

        # ===== 阶段 2 新增：再沸/冷凝/气相库存参数校验（todo/5.md §3.2、§5、§6） =====
        for name in (
            "steam_latent_heat_kj_per_kg",
            "cooling_water_cp_kj_per_kg_k",
            "condenser_ua_kw_per_k",
            "cooling_water_design_delta_t_k",
            "p_vapor_floor_kpa",
            "tau_condenser_inventory_s",
            "tau_sump_heat_s",
            "tau_phase_s",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"参数无效: {name} 必须为有限数值，实际值={value!r}")
            if float(value) <= 0.0:
                raise ValueError(f"{name} 必须严格大于0，实际值={value!r}")

        # 蒸汽侧传热效率 ∈ (0, 1]
        eff = float(self.steam_heat_transfer_efficiency)
        if not math.isfinite(eff) or eff <= 0.0 or eff > 1.0:
            raise ValueError(
                f"steam_heat_transfer_efficiency 必须位于 (0, 1]，实际值={eff!r}"
            )

        # 气相库存下限压力合理范围（spec §6.4：p_vapor_floor_kpa > 0 且 < 50 kPa 不合理）
        # 注：spec §2.15 要求 p_vapor_floor_kpa > 0 且 < 50 kPa 是错的（应为下限本身合理）
        # 实际逻辑：p_vapor_floor_kpa 必须为正且小于常压（< 101.325 kPa）
        pf = float(self.p_vapor_floor_kpa)
        if pf >= 101.325:
            raise ValueError(
                f"p_vapor_floor_kpa 必须小于常压 101.325 kPa，实际值={pf!r}"
            )

        # 放空流量（第一版关闭，允许 0；不得为负）
        vf = float(self.vent_flow_kgmol_per_s)
        if not math.isfinite(vf) or vf < 0.0:
            raise ValueError(
                f"vent_flow_kgmol_per_s 不得为负，实际值={vf!r}"
            )

        mode = str(self.initialization_mode).upper()
        if mode not in ("STEADY", "COLD", "WARM_GUESS"):
            raise ValueError(
                f"initialization_mode 必须为 'STEADY' / 'WARM_GUESS' / 'COLD'，"
                f"实际值={self.initialization_mode!r}"
            )
        if mode == "COLD":
            raise NotImplementedError(
                "initialization_mode=COLD 第一版未实现（spec §10.3），后续阶段单独设计"
            )

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _load_or_build_initial_state(self) -> None:
        """
        初始化分发器（todo/5.md §10 + 阶段 4.1 修正）。

        阶段 4.1 明确语义：
        - WARM_GUESS：建立线性浓度和泡点初猜，仅供稳态生成器使用；
        - STEADY：必须加载合格参考状态（文件缺失/哈希不匹配/验收未通过必须报错，
                  不得回退到初猜）；
        - COLD：继续抛出 NotImplementedError。

        阶段 4.1 之前：STEADY 静默回退到 warm_guess 初猜（错误）。
        阶段 4.1 修正：STEADY 严格模式，强制要求参考文件存在并通过验收。
        """
        mode = str(self.initialization_mode).upper()

        if mode == "WARM_GUESS":
            # 仅建立线性+泡点初猜，不加载参考文件
            self._build_warm_guess_initial_state()
            return

        if mode == "STEADY":
            # 必须加载合格参考状态，不得回退
            self._load_steady_reference_state_strict()
            return

        # COLD 已在 _validate_configuration 中拦截，但防御性处理
        raise NotImplementedError(
            "initialization_mode=COLD 第一版未实现（spec §10.3），后续阶段单独设计"
        )

    # ------------------------------------------------------------------
    def _build_warm_guess_initial_state(self) -> None:
        """
        WARM_GUESS 初始化：建立线性浓度和泡点初猜（todo/5.md §10.2）。

        用线性插值生成接近稳态的浓度剖面，然后用泡点计算初始温度，
        最后由温度反算初始内能 U，保证 U 与 T 在初始时刻一致。

        气相存量 N_vapor 由初始 P_top 和 V_gas 通过理想气体状态方程反算。

        注意：此初猜仅供稳态生成器使用，正式运行应使用 STEADY 模式加载
        合格参考状态。
        """
        # 目标塔顶/塔底乙醇摩尔分数（来自 spec §2.3 参考工况）
        x_top_target_mol = ethanol_mass_fraction_to_mole_fraction(0.85)
        x_bottom_target_mol = ethanol_mass_fraction_to_mole_fraction(0.015)
        x_feed_mol = ethanol_mass_fraction_to_mole_fraction(self.feed_ethanol_wt)

        # 浓度剖面（线性插值）
        x_e = np.zeros(self._n_trays, dtype=np.float64)
        feed_idx = self._feed_stage_idx  # 0-indexed
        for i in range(self._n_trays):
            if i <= feed_idx:
                if feed_idx > 0:
                    t = i / feed_idx
                    x_e[i] = x_top_target_mol * (1.0 - t) + x_feed_mol * t
                else:
                    x_e[i] = x_top_target_mol
            else:
                t = (i - feed_idx) / (self._n_trays - 1 - feed_idx)
                x_e[i] = x_feed_mol * (1.0 - t) + x_bottom_target_mol * t

        x_e = np.clip(x_e, 0.0, 1.0)

        # 持液量（标称值）
        m_tray = np.full(self._n_trays, self._m_tray_nom, dtype=np.float64)
        m_drum = self._m_drum_nom
        m_sump = self._m_sump_nom
        x_e_drum = x_top_target_mol
        x_e_sump = x_bottom_target_mol

        # 用泡点计算初始温度（使系统初始处于 VLE 平衡）
        # 用设定压力剖面初始化
        v_init = float(self.vapor_boilup_kgmol_per_s)
        p_top_init = self._p_top_setpoint_kpa
        pressure_kpa_init = np.empty(self._n_trays, dtype=np.float64)
        pressure_kpa_init[0] = p_top_init
        for i in range(1, self._n_trays):
            dp = self._pressure_drop_dry_kpa + self._pressure_drop_kv * v_init * v_init
            pressure_kpa_init[i] = pressure_kpa_init[i - 1] + dp
        p_sump_init = pressure_kpa_init[-1] + self._pressure_drop_dry_kpa + \
            self._pressure_drop_kv * v_init * v_init

        T_tray_init = np.zeros(self._n_trays, dtype=np.float64)
        yE_tray_init = np.zeros(self._n_trays, dtype=np.float64)
        for i in range(self._n_trays):
            T_tray_init[i], yE_tray_init[i] = bubble_point_temperature(
                float(x_e[i]), float(pressure_kpa_init[i])
            )
        T_sump_init, yE_sump_init = bubble_point_temperature(
            float(x_e_sump), float(p_sump_init)
        )
        # 回流罐温度 = 塔顶板温度（全凝器饱和液体）
        T_drum_init = float(T_tray_init[0])

        # 由温度反算内能 U = M * h_L_mix(x, T)
        U_tray_init = np.array(
            [m_tray[i] * liquid_enthalpy_kj_per_kmol(float(x_e[i]), float(T_tray_init[i]))
             for i in range(self._n_trays)],
            dtype=np.float64,
        )
        U_drum_init = m_drum * liquid_enthalpy_kj_per_kmol(float(x_e_drum), float(T_drum_init))
        U_sump_init = m_sump * liquid_enthalpy_kj_per_kmol(float(x_e_sump), float(T_sump_init))

        # 气相存量 N_vapor（由 P_top 和 V_gas 反算）
        T_vapor_avg_init = float(np.mean(T_tray_init))
        N_vapor_init = (
            p_top_init * self._vapor_volume_m3
            / (R_UNIVERSAL_KPA_M3_PER_KMOL_K * T_vapor_avg_init)
        )

        # ===== 阶段 2 新增：气相乙醇物质量和气相内能（spec §6.1） =====
        # 初始 yE_vapor = 塔顶板气相组成（spec §2.2 初始化要求）
        yE_vapor_init = float(yE_tray_init[0])
        yE_vapor_init = max(0.0, min(1.0, yE_vapor_init))
        # 初始 T_vapor = 塔板平均温度（spec §2.2）
        T_vapor_init = T_vapor_avg_init
        # 初始 U_vapor = N_vapor * u_vapor_per_kmol(yE_vapor, T_vapor)
        u_vapor_per_kmol_init = vapor_internal_energy_kj_per_kmol(yE_vapor_init, T_vapor_init)
        U_vapor_init = N_vapor_init * u_vapor_per_kmol_init  # kJ
        # 初始 nE_vapor = N_vapor * yE_vapor
        nE_vapor_init = N_vapor_init * yE_vapor_init  # kmol

        # 状态数组
        self._M_tray = m_tray.copy()                  # kmol
        self._nE_tray = m_tray * x_e                  # kmol
        self._U_tray = U_tray_init                    # kJ
        self._M_drum = m_drum                          # kmol
        self._nE_drum = m_drum * x_e_drum             # kmol
        self._U_drum = U_drum_init                    # kJ
        self._M_sump = m_sump                          # kmol
        self._nE_sump = m_sump * x_e_sump             # kmol
        self._U_sump = U_sump_init                    # kJ
        self._N_vapor = N_vapor_init                  # kmol
        # 阶段 2 新增气相状态
        self._nE_vapor = nE_vapor_init                # kmol
        self._U_vapor = U_vapor_init                  # kJ

        # 气相流量（CMO 假设）
        self._V_kgmol_per_s = v_init

        # 派生量（由 _compute_algebraic 计算）
        self._T_tray = T_tray_init.copy()
        self._yE_tray = yE_tray_init.copy()
        self._T_drum = T_drum_init
        self._T_sump = T_sump_init
        self._yE_sump = yE_sump_init
        self._pressure_kpa = pressure_kpa_init.copy()
        self._p_top_kpa = p_top_init
        self._p_sump_kpa = p_sump_init
        self._T_vapor_avg = T_vapor_avg_init
        # 阶段 2 派生量：气相组成和温度（由内能反算）
        self._yE_vapor = yE_vapor_init
        self._T_vapor = T_vapor_init

        # 上次流量输入（用于残差诊断和首次 execute 默认值）
        self._last_feed_flow = float(self.feed_flow_kgmol_per_s)
        self._last_reflux_flow = float(self.reflux_flow_kgmol_per_s)
        self._last_distillate_flow = float(self.distillate_flow_kgmol_per_s)
        self._last_bottoms_flow = float(self.bottoms_flow_kgmol_per_s)
        self._last_vapor_boilup = float(self.vapor_boilup_kgmol_per_s)

        # 阶段 C 输出
        self.reboiler_duty_kw = 0.0
        self.condenser_duty_kw = 0.0
        self.energy_balance_residual_kw = 0.0
        # 阶段 3.2 新增：明确闭合残差位号（兼容位号继续指向 closure residual）
        self.mass_closure_residual_kg_h = 0.0
        self.ethanol_closure_residual_kg_h = 0.0
        self.energy_closure_residual_kw = 0.0
        self.mass_balance_residual_kg_h = 0.0
        self.ethanol_balance_residual_kg_h = 0.0
        # 内部用的再沸/冷凝负荷（首次 execute 前的默认值）
        self._Q_R_kw = 0.0
        self._Q_C_kw = 0.0
        # 阶段 2 新增：内部 V_boil 和 V_condense（避免与外部输入冲突）
        # 初始用 nominal vapor_boilup 作为初值，第一次 execute 后由 Q_R 反推
        self._V_boil_internal = float(self.vapor_boilup_kgmol_per_s)
        self._V_condense_internal = float(self.vapor_boilup_kgmol_per_s)
        # 阶段 2 新增：守恒积累率位号初值（spec §11）
        self.mass_accumulation_kg_h = 0.0
        self.ethanol_accumulation_kg_h = 0.0
        self.energy_accumulation_kw = 0.0
        # 阶段 2 新增：发布位号初值
        self.vapor_condense_kgmol_per_s = float(self._V_condense_internal)
        self.vapor_boilup_kgmol_per_s_internal = float(self._V_boil_internal)
        self.ethanol_recovery_pct = 0.0
        self.qualified_product_flow_kg_h = 0.0
        self.specific_steam_kg_per_kg_product = 0.0
        self.raw_reflux_drum_level_pct = 0.0
        self.raw_reboiler_level_pct = 0.0
        self.vapor_ethanol_y = float(self._yE_vapor)
        self.vapor_temperature_c = float(self._T_vapor - 273.15)

        # 累计守恒诊断
        self._cumulative_mass_in = 0.0     # kg
        self._cumulative_mass_out = 0.0    # kg
        self._cumulative_ethanol_in = 0.0  # kg
        self._cumulative_ethanol_out = 0.0 # kg
        self._cumulative_energy_in = 0.0   # kJ
        self._cumulative_energy_out = 0.0  # kJ
        self._initial_total_mass = 0.0     # kg
        self._initial_total_ethanol = 0.0  # kg
        self._initial_total_energy = 0.0   # kJ
        self._first_execute = True
        # 阶段 2 新增：上一期总存量（用于闭合残差计算，spec §11）
        self._prev_M_total_kgmol = 0.0
        self._prev_nE_total_kgmol = 0.0
        self._prev_U_total_kj = 0.0

    # ------------------------------------------------------------------
    def _load_steady_reference_state_strict(self) -> None:
        """
        STEADY 模式：严格加载合格参考状态（todo/5.md §10.2 + 阶段 4.1 + todo/6.md §7）。

        严格语义：
        - 参考文件必须存在；
        - 参数哈希必须匹配；
        - 版本必须匹配；
        - 元数据门禁（todo/6.md §7.1）：
            model_name == "ETHANOL_WATER_DISTILLATION"
            used_direct_vapor_bypass is False（必须显式存在）
            skip_long_validation is False（必须显式存在）
            solver_status > 0
            solver_max_residual <= 1.0
            solver_cost / solver_optimality / solver_max_residual 必须为有限数
        - 验收状态门禁（todo/6.md §7.2）：
            convergence.passed is True
            convergence.mode_equivalence_passed is True
            convergence.drift_passed is True
            convergence.convergence_window_cycles >= 3600
        - 收敛指标门禁（todo/6.md §7.3）：全部 16 项
        - 漂移指标门禁（todo/6.md §7.4）：全部 7 项
        - 状态数组门禁（todo/6.md §7.5）：
            M_tray / nE_tray / U_tray / T_tray / yE_tray / pressure_kpa
            必须存在、一维、长度 12、全部有限、满足基本物理关系
            13 个标量必须存在、有限、满足基本物理关系

        任何一项不满足都抛出 ValueError，不得静默回退到 warm_guess。

        通用 load_state() 是运行时快照恢复接口，可保持宽松；正式 STEADY 必须走严格检查。

        Raises:
            FileNotFoundError: 参考稳态文件不存在。
            ValueError: 任何门禁失败。
        """
        import json
        import os

        file_path = str(self.reference_state_file)
        if not os.path.isabs(file_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            file_path = os.path.join(project_root, file_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"initialization_mode=STEADY 要求参考稳态文件存在，但未找到: {file_path}\n"
                f"请先运行 tools/generate_ethanol_water_reference_state.py 生成参考状态。"
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(
                f"参考稳态文件读取失败: {e}"
            ) from e

        # ----------------------------------------------------------------
        # 局部辅助函数（todo/6.md §7.5）
        # ----------------------------------------------------------------
        def _require_finite_number(mapping, key, section):
            if key not in mapping:
                raise ValueError(
                    f"参考稳态 {section} 缺少必需字段: {key}"
                )
            try:
                value = float(mapping[key])
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"参考稳态 {section}.{key} 无法转换为数值: {mapping[key]!r}"
                ) from e
            if not math.isfinite(value):
                raise ValueError(
                    f"参考稳态 {section}.{key} 非有限数: {value}"
                )
            return value

        def _require_bool(mapping, key, expected, section):
            if key not in mapping:
                raise ValueError(
                    f"参考稳态 {section} 缺少必需布尔字段: {key}"
                )
            value = mapping[key]
            # 严格 isinstance(bool) 检查，拒绝字符串 "true" 等宽松真值
            if not isinstance(value, bool):
                raise ValueError(
                    f"参考稳态 {section}.{key} 必须为 bool 类型，实际 {type(value).__name__}: {value!r}"
                )
            if value is not expected:
                raise ValueError(
                    f"参考稳态 {section}.{key} 必须为 {expected}，实际 {value}"
                )
            return value

        def _require_finite_array(mapping, key, expected_len):
            if key not in mapping:
                raise ValueError(
                    f"参考稳态状态缺少必需数组: {key}"
                )
            arr = mapping[key]
            try:
                arr_np = np.asarray(arr, dtype=np.float64)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"参考稳态状态数组 {key} 无法转换为 float64: {e}"
                ) from e
            if arr_np.ndim != 1:
                raise ValueError(
                    f"参考稳态状态数组 {key} 必须为一维，实际 ndim={arr_np.ndim}"
                )
            if arr_np.shape[0] != expected_len:
                raise ValueError(
                    f"参考稳态状态数组 {key} 长度必须为 {expected_len}，实际 {arr_np.shape[0]}"
                )
            if not np.all(np.isfinite(arr_np)):
                bad_idx = np.where(~np.isfinite(arr_np))[0]
                raise ValueError(
                    f"参考稳态状态数组 {key} 包含 NaN/Inf，位置: {bad_idx.tolist()}"
                )
            return arr_np

        # ----------------------------------------------------------------
        # §7.1 元数据门禁
        # ----------------------------------------------------------------
        metadata = state.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(
                f"参考稳态 metadata 必须为字典，实际 {type(metadata).__name__}"
            )

        expected_model = metadata.get("model_name", "")
        if expected_model != "ETHANOL_WATER_DISTILLATION":
            raise ValueError(
                f"参考稳态文件 model_name 不匹配: 期望 ETHANOL_WATER_DISTILLATION，实际 {expected_model!r}"
            )

        # used_direct_vapor_bypass / skip_long_validation 必须显式存在且为 False
        _require_bool(metadata, "used_direct_vapor_bypass", False, "metadata")
        _require_bool(metadata, "skip_long_validation", False, "metadata")

        # solver_status 必须为正
        solver_status_raw = metadata.get("solver_status")
        if not isinstance(solver_status_raw, (int, np.integer)):
            raise ValueError(
                f"参考稳态 metadata.solver_status 必须为整数，实际 {type(solver_status_raw).__name__}: {solver_status_raw!r}"
            )
        solver_status = int(solver_status_raw)
        if solver_status <= 0:
            raise ValueError(
                f"参考稳态 metadata.solver_status 必须 > 0，实际 {solver_status}"
            )

        # solver_cost / solver_optimality / solver_max_residual 必须有限
        solver_cost = _require_finite_number(metadata, "solver_cost", "metadata")
        solver_optimality = _require_finite_number(metadata, "solver_optimality", "metadata")
        solver_max_residual = _require_finite_number(metadata, "solver_max_residual", "metadata")
        if solver_max_residual > 1.0:
            raise ValueError(
                f"参考稳态 metadata.solver_max_residual 必须 <= 1.0，实际 {solver_max_residual}"
            )

        # 参数哈希和版本（保留现有检查）
        file_hash = state.get("params_hash", "")
        current_hash = self._compute_params_hash()
        if file_hash != current_hash:
            raise ValueError(
                f"参考稳态参数哈希不匹配: 文件={file_hash}, 当前={current_hash}\n"
                f"请重新生成参考状态（运行 tools/generate_ethanol_water_reference_state.py）"
            )

        file_version = state.get("version", "")
        if file_version != self.REFERENCE_STATE_VERSION:
            raise ValueError(
                f"参考稳态版本不匹配: 文件={file_version}, 当前={self.REFERENCE_STATE_VERSION}\n"
                f"请重新生成参考状态"
            )

        # ----------------------------------------------------------------
        # §7.2 验收状态门禁
        # ----------------------------------------------------------------
        convergence = state.get("convergence", {})
        if not isinstance(convergence, dict):
            raise ValueError(
                f"参考稳态 convergence 必须为字典，实际 {type(convergence).__name__}"
            )

        _require_bool(convergence, "passed", True, "convergence")
        _require_bool(convergence, "mode_equivalence_passed", True, "convergence")
        _require_bool(convergence, "drift_passed", True, "convergence")

        convergence_window_cycles_raw = convergence.get("convergence_window_cycles")
        if not isinstance(convergence_window_cycles_raw, (int, np.integer)):
            raise ValueError(
                f"参考稳态 convergence.convergence_window_cycles 必须为整数，"
                f"实际 {type(convergence_window_cycles_raw).__name__}: {convergence_window_cycles_raw!r}"
            )
        convergence_window_cycles = int(convergence_window_cycles_raw)
        if convergence_window_cycles < 3600:
            raise ValueError(
                f"参考稳态 convergence.convergence_window_cycles 必须 >= 3600，实际 {convergence_window_cycles}"
            )

        # ----------------------------------------------------------------
        # §7.3 收敛指标门禁（16 项）
        # ----------------------------------------------------------------
        convergence_thresholds = [
            ("max_abs_dM_tray_dt", 1e-8, "le"),
            ("max_abs_dnE_tray_dt", 1e-9, "le"),
            ("abs_dM_drum_dt", 1e-8, "le"),
            ("abs_dM_sump_dt", 1e-8, "le"),
            ("abs_dN_vapor_dt", 1e-9, "le"),
            ("abs_dP_top_dt", 1e-4, "le"),
            ("max_abs_dT_dt", 1e-4, "le"),
            ("mass_residual_rel", 0.001, "le"),
            ("ethanol_residual_rel", 0.002, "le"),
            ("energy_residual_rel", 0.01, "le"),
            ("ethanol_recovery_pct", 95.0, "ge"),
        ]
        for key, threshold, op in convergence_thresholds:
            value = _require_finite_number(convergence, key, "convergence")
            if op == "le" and value > threshold:
                raise ValueError(
                    f"参考稳态 convergence.{key} 超阈值: {value} > {threshold}"
                )
            if op == "ge" and value < threshold:
                raise ValueError(
                    f"参考稳态 convergence.{key} 低于阈值: {value} < {threshold}"
                )

        # 范围类指标
        drum_level_pct = _require_finite_number(convergence, "drum_level_pct", "convergence")
        sump_level_pct = _require_finite_number(convergence, "sump_level_pct", "convergence")
        top_pressure_kpa = _require_finite_number(convergence, "top_pressure_kpa", "convergence")
        top_ethanol_wt = _require_finite_number(convergence, "top_ethanol_wt", "convergence")
        bottom_ethanol_wt = _require_finite_number(convergence, "bottom_ethanol_wt", "convergence")

        if not (47.0 <= drum_level_pct <= 53.0):
            raise ValueError(
                f"参考稳态 convergence.drum_level_pct 超范围 [47, 53]: {drum_level_pct}"
            )
        if not (47.0 <= sump_level_pct <= 53.0):
            raise ValueError(
                f"参考稳态 convergence.sump_level_pct 超范围 [47, 53]: {sump_level_pct}"
            )
        if abs(top_pressure_kpa - 101.325) > 0.10:
            raise ValueError(
                f"参考稳态 convergence.top_pressure_kpa 偏离 101.325 超过 0.10 kPa: {top_pressure_kpa}"
            )
        if not (0.82 <= top_ethanol_wt <= 0.88):
            raise ValueError(
                f"参考稳态 convergence.top_ethanol_wt 超范围 [0.82, 0.88]: {top_ethanol_wt}"
            )
        if not (0.010 <= bottom_ethanol_wt <= 0.020):
            raise ValueError(
                f"参考稳态 convergence.bottom_ethanol_wt 超范围 [0.010, 0.020]: {bottom_ethanol_wt}"
            )

        # ----------------------------------------------------------------
        # §7.4 漂移指标门禁（7 项）
        # ----------------------------------------------------------------
        drift = convergence.get("drift", {})
        if not isinstance(drift, dict):
            raise ValueError(
                f"参考稳态 convergence.drift 必须为字典，实际 {type(drift).__name__}"
            )

        drift_thresholds = [
            ("pressure_drift_kpa", 0.10),
            ("drum_level_drift_pct", 1.0),
            ("sump_level_drift_pct", 1.0),
            ("top_temp_drift_c", 0.20),
            ("bottom_temp_drift_c", 0.20),
            ("top_x_drift", 0.003),
            ("bottom_x_drift", 0.001),
        ]
        for key, threshold in drift_thresholds:
            value = _require_finite_number(drift, key, "convergence.drift")
            if value > threshold:
                raise ValueError(
                    f"参考稳态 convergence.drift.{key} 超阈值: {value} > {threshold}"
                )

        # ----------------------------------------------------------------
        # §7.5 状态数组门禁
        # ----------------------------------------------------------------
        M_tray_arr = _require_finite_array(state, "M_tray", 12)
        nE_tray_arr = _require_finite_array(state, "nE_tray", 12)
        U_tray_arr = _require_finite_array(state, "U_tray", 12)
        T_tray_arr = _require_finite_array(state, "T_tray", 12)
        yE_tray_arr = _require_finite_array(state, "yE_tray", 12)
        pressure_kpa_arr = _require_finite_array(state, "pressure_kpa", 12)

        # 基本物理关系
        if not np.all(M_tray_arr > 0):
            bad_idx = np.where(M_tray_arr <= 0)[0]
            raise ValueError(
                f"参考稳态 M_tray 必须全部为正，违规位置: {bad_idx.tolist()}, 值: {M_tray_arr[bad_idx].tolist()}"
            )
        if not np.all((nE_tray_arr >= 0) & (nE_tray_arr <= M_tray_arr)):
            bad_idx = np.where(~((nE_tray_arr >= 0) & (nE_tray_arr <= M_tray_arr)))[0]
            raise ValueError(
                f"参考稳态 nE_tray 必须 0 <= nE <= M，违规位置: {bad_idx.tolist()}"
            )
        if not np.all((yE_tray_arr >= 0) & (yE_tray_arr <= 1)):
            bad_idx = np.where(~((yE_tray_arr >= 0) & (yE_tray_arr <= 1)))[0]
            raise ValueError(
                f"参考稳态 yE_tray 必须 0 <= yE <= 1，违规位置: {bad_idx.tolist()}"
            )
        if not np.all(pressure_kpa_arr > 0):
            bad_idx = np.where(pressure_kpa_arr <= 0)[0]
            raise ValueError(
                f"参考稳态 pressure_kpa 必须全部为正，违规位置: {bad_idx.tolist()}"
            )

        # 13 个标量
        M_drum = _require_finite_number(state, "M_drum", "state")
        nE_drum = _require_finite_number(state, "nE_drum", "state")
        U_drum = _require_finite_number(state, "U_drum", "state")
        M_sump = _require_finite_number(state, "M_sump", "state")
        nE_sump = _require_finite_number(state, "nE_sump", "state")
        U_sump = _require_finite_number(state, "U_sump", "state")
        N_vapor = _require_finite_number(state, "N_vapor", "state")
        nE_vapor = _require_finite_number(state, "nE_vapor", "state")
        U_vapor = _require_finite_number(state, "U_vapor", "state")
        T_drum = _require_finite_number(state, "T_drum", "state")
        T_sump = _require_finite_number(state, "T_sump", "state")
        T_vapor = _require_finite_number(state, "T_vapor", "state")
        p_top_kpa = _require_finite_number(state, "p_top_kpa", "state")
        p_sump_kpa = _require_finite_number(state, "p_sump_kpa", "state")

        # 基本物理关系
        if M_drum <= 0:
            raise ValueError(f"参考稳态 M_drum 必须为正，实际 {M_drum}")
        if not (0 <= nE_drum <= M_drum):
            raise ValueError(f"参考稳态 nE_drum 必须 0 <= nE <= M_drum，实际 nE={nE_drum}, M={M_drum}")
        if M_sump <= 0:
            raise ValueError(f"参考稳态 M_sump 必须为正，实际 {M_sump}")
        if not (0 <= nE_sump <= M_sump):
            raise ValueError(f"参考稳态 nE_sump 必须 0 <= nE <= M_sump，实际 nE={nE_sump}, M={M_sump}")
        if N_vapor <= 0:
            raise ValueError(f"参考稳态 N_vapor 必须为正，实际 {N_vapor}")
        if not (0 <= nE_vapor <= N_vapor):
            raise ValueError(f"参考稳态 nE_vapor 必须 0 <= nE <= N_vapor，实际 nE={nE_vapor}, N={N_vapor}")
        if not (70 <= p_top_kpa <= 160):
            raise ValueError(f"参考稳态 p_top_kpa 超范围 [70, 160]: {p_top_kpa}")
        if p_sump_kpa < p_top_kpa:
            raise ValueError(
                f"参考稳态 p_sump_kpa 必须 >= p_top_kpa，实际 p_sump={p_sump_kpa}, p_top={p_top_kpa}"
            )

        # ----------------------------------------------------------------
        # 所有关卡通过，加载状态
        # ----------------------------------------------------------------
        try:
            self._set_full_state_dict(state)
        except ValueError as e:
            raise ValueError(
                f"参考稳态状态恢复失败: {e}"
            ) from e

        self._reference_state_path = file_path
        self._reference_state_loaded = True
        logger.info(
            f"参考稳态已加载（STEADY 严格模式）: {file_path}\n"
            f"  solver: status={solver_status}, cost={solver_cost:.4e}, "
            f"optimality={solver_optimality:.4e}, max_residual={solver_max_residual:.4e}\n"
            f"  收敛: mass={convergence['mass_residual_rel']:.2e}, "
            f"ethanol={convergence['ethanol_residual_rel']:.2e}, "
            f"energy={convergence['energy_residual_rel']:.2e}\n"
            f"  漂移: P={drift['pressure_drift_kpa']:.4f} kPa, "
            f"drum={drift['drum_level_drift_pct']:.4f}%, sump={drift['sump_level_drift_pct']:.4f}%"
        )

    # ------------------------------------------------------------------
    # 代数量计算（VLE、温度、压力、流量）
    # ------------------------------------------------------------------
    def _compute_algebraic(
        self,
        M_tray: np.ndarray,
        nE_tray: np.ndarray,
        U_tray: np.ndarray,
        M_drum: float,
        nE_drum: float,
        U_drum: float,
        M_sump: float,
        nE_sump: float,
        U_sump: float,
        N_vapor: float,
        nE_vapor: float,
        U_vapor: float,
        V: float,
    ) -> Tuple[np.ndarray, np.ndarray, float, float, float, float, np.ndarray, float, float, float, float]:
        """
        由状态计算代数量：温度、气相组成、压力剖面、平均气相温度。

        阶段 2 新增：气相组成 yE_vapor 和气相温度 T_vapor 由 (nE_vapor, U_vapor, N_vapor) 反算。
        P_top 由 N_vapor, T_vapor 计算（不再用 T_vapor_avg）。

        Args:
            M_tray, nE_tray, U_tray: 塔板液相物质量、乙醇物质量、内能 (12,)
            M_drum, nE_drum, U_drum: 回流罐
            M_sump, nE_sump, U_sump: 塔釜
            N_vapor: 气相总存量 (kmol)
            nE_vapor: 气相乙醇物质量 (kmol)
            U_vapor: 气相总内能 (kJ)
            V: 气相流量 (kmol/s, CMO)

        Returns:
            (T_tray, yE_tray, T_drum, T_sump, yE_sump, p_top, pressure_kpa, p_sump,
             T_vapor_avg, yE_vapor, T_vapor)
        """
        # 液相组成（截断到 [0,1]）
        xE_tray = np.where(M_tray > 1e-15, nE_tray / M_tray, 0.0)
        xE_tray = np.clip(xE_tray, 0.0, 1.0)
        xE_drum = nE_drum / M_drum if M_drum > 1e-15 else 0.0
        xE_drum = max(0.0, min(1.0, xE_drum))
        xE_sump = nE_sump / M_sump if M_sump > 1e-15 else 0.0
        xE_sump = max(0.0, min(1.0, xE_sump))

        # 塔板温度：由内能反算 T = T_ref + U / (M * Cp_L_mix(x))
        T_tray = np.empty(self._n_trays, dtype=np.float64)
        for i in range(self._n_trays):
            cp_mix = liquid_heat_capacity_kj_per_kmol_k(float(xE_tray[i]))
            T_tray[i] = T_REF_K + U_tray[i] / (M_tray[i] * cp_mix)
            # 物理范围限制（数值保护，避免极端情况）
            if not math.isfinite(T_tray[i]):
                T_tray[i] = T_REF_K + 50.0
            T_tray[i] = max(250.0, min(500.0, T_tray[i]))

        # 回流罐和塔釜温度
        cp_drum = liquid_heat_capacity_kj_per_kmol_k(xE_drum)
        T_drum = T_REF_K + U_drum / (M_drum * cp_drum)
        if not math.isfinite(T_drum):
            T_drum = T_REF_K + 50.0
        T_drum = max(250.0, min(500.0, T_drum))

        cp_sump = liquid_heat_capacity_kj_per_kmol_k(xE_sump)
        T_sump = T_REF_K + U_sump / (M_sump * cp_sump)
        if not math.isfinite(T_sump):
            T_sump = T_REF_K + 50.0
        T_sump = max(250.0, min(500.0, T_sump))

        # ===== 阶段 2 新增：气相组成和温度（由 nE_vapor, U_vapor 反算） =====
        # yE_vapor = nE_vapor / N_vapor（裁剪 [0,1]）
        if N_vapor > 1e-15:
            yE_vapor = nE_vapor / N_vapor
        else:
            yE_vapor = 0.0
        yE_vapor = max(0.0, min(1.0, yE_vapor))
        # u_vapor_per_kmol = U_vapor / N_vapor
        if N_vapor > 1e-15:
            u_vapor_per_kmol = U_vapor / N_vapor
        else:
            u_vapor_per_kmol = 0.0
        # T_vapor = temperature_from_vapor_internal_energy(u, yE_vapor)
        try:
            T_vapor = temperature_from_vapor_internal_energy(u_vapor_per_kmol, yE_vapor)
        except (ValueError, ZeroDivisionError):
            T_vapor = self._T_vapor_avg if hasattr(self, "_T_vapor_avg") else 350.0
        if not math.isfinite(T_vapor):
            T_vapor = 350.0
        # T_vapor 范围保护 [250, 500] K
        T_vapor = max(250.0, min(500.0, T_vapor))

        # 塔顶压力：理想气体状态方程 P = N·R·T_vapor / V（阶段 2 用 T_vapor）
        if T_vapor <= 0.0 or not math.isfinite(T_vapor):
            T_vapor = 350.0
        p_top = N_vapor * R_UNIVERSAL_KPA_M3_PER_KMOL_K * T_vapor / self._vapor_volume_m3
        if not math.isfinite(p_top) or p_top <= 0.0:
            p_top = self._p_top_setpoint_kpa  # 数值保护

        # 沿塔压降 ΔP_i = ΔP_dry + K_v · V²
        dp = self._pressure_drop_dry_kpa + self._pressure_drop_kv * V * V
        pressure_kpa = np.empty(self._n_trays, dtype=np.float64)
        pressure_kpa[0] = p_top
        for i in range(1, self._n_trays):
            pressure_kpa[i] = pressure_kpa[i - 1] + dp
        p_sump = pressure_kpa[-1] + dp

        # 气相组成：VLE at (T, x, P)，归一化以兼容非平衡态
        yE_tray = np.empty(self._n_trays, dtype=np.float64)
        for i in range(self._n_trays):
            y_e, _, _ = vapor_composition_at_state(
                float(xE_tray[i]), float(T_tray[i]), float(pressure_kpa[i])
            )
            yE_tray[i] = max(0.0, min(1.0, y_e))

        # 塔釜气相组成
        y_e_sump, _, _ = vapor_composition_at_state(xE_sump, T_sump, p_sump)
        y_e_sump = max(0.0, min(1.0, y_e_sump))

        # T_vapor_avg 仍计算用于诊断和对外位号
        T_vapor_avg = float(np.mean(T_tray))
        if T_vapor_avg <= 0.0 or not math.isfinite(T_vapor_avg):
            T_vapor_avg = 350.0

        return (T_tray, yE_tray, T_drum, T_sump, y_e_sump, p_top, pressure_kpa, p_sump,
                T_vapor_avg, yE_vapor, T_vapor)

    # ------------------------------------------------------------------
    # 水力学
    # ------------------------------------------------------------------
    def _calculate_hydraulics(self, M_tray: np.ndarray) -> np.ndarray:
        """
        计算向下液相流量 L[i] (kmol/s)。

        简化堰流公式（spec §5.5）：
            L[i] = L_nom[i] * (M[i] / M_nom[i])^1.5
        """
        r_nom = float(self.reflux_flow_kgmol_per_s)
        f_nom = float(self.feed_flow_kgmol_per_s)
        l_nom = np.empty(self._n_trays, dtype=np.float64)
        for i in range(self._n_trays):
            if i < self._feed_stage_idx:
                l_nom[i] = r_nom
            else:
                l_nom[i] = r_nom + f_nom

        ratio = M_tray / self._m_tray_nom
        ratio = np.clip(ratio, 0.0, None)
        return l_nom * np.power(ratio, 1.5)

    # ------------------------------------------------------------------
    # RHS（状态导数）
    # ------------------------------------------------------------------
    def _calculate_rhs(
        self,
        M_tray: np.ndarray,
        nE_tray: np.ndarray,
        U_tray: np.ndarray,
        M_drum: float,
        nE_drum: float,
        U_drum: float,
        M_sump: float,
        nE_sump: float,
        U_sump: float,
        N_vapor: float,
        nE_vapor: float,
        U_vapor: float,
        L: np.ndarray,
        V: float,
        T_tray: np.ndarray,
        yE_tray: np.ndarray,
        T_drum: float,
        T_sump: float,
        yE_sump: float,
        T_vapor: float,
        yE_vapor: float,
        p_top: float,
        p_sump: float,
        feed_flow: float,
        feed_xE: float,
        feed_temperature_k: float,
        reflux_flow: float,
        distillate_flow: float,
        bottoms_flow: float,
        steam_flow_kg_h: float,
        cooling_flow_kg_h: float,
        cooling_water_temperature_c: float,
        direct_vapor_bypass: Optional[float] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, float, float, float, float, float, float]:
        """
        计算状态导数：(dM, dnE, dU) for tray/drum/sump + (dN_vapor, dnE_vapor, dU_vapor)。

        阶段 2 修改（todo/5.md §5.2、§6.3、§6.4、§6.5、§6.6）：
        - Q_R 由蒸汽流量反推（不再由 V_boilup 反推）
        - V_boil 由 Q_for_vaporization / ΔH_vap_sump 决定
        - V_condense 由冷却能力决定（允许消耗气相库存）
        - 塔板 vapor_boilup 改为内部 V_boil
        - 回流罐入口使用 V_condense（不是 V_top）
        - 新增气相动态：dN_v/dt、dnE_v/dt、dU_v/dt

        Args:
            direct_vapor_bypass: 阶段 2 兼容路径：直接流量模式下，
                若调用方显式传入 vapor_boilup_kgmol_per_s，则跳过 Q_R → V_boil
                机理，直接使用该值作为 V_boil（spec §5.2 标注为 bypass）。

        返回顺序：
            dM_tray, dnE_tray, dU_tray,
            dM_drum, dnE_drum, dU_drum,
            dM_sump, dnE_sump, dU_sump,
            dN_vapor, dnE_vapor, dU_vapor
        """
        n_trays = self._n_trays
        feed_idx = self._feed_stage_idx
        T_amb = self._ambient_temperature_k

        # 液相组成
        xE_tray = np.where(M_tray > 1e-15, nE_tray / M_tray, 0.0)
        xE_tray = np.clip(xE_tray, 0.0, 1.0)
        xE_drum = nE_drum / M_drum if M_drum > 1e-15 else 0.0
        xE_drum = max(0.0, min(1.0, xE_drum))
        xE_sump = nE_sump / M_sump if M_sump > 1e-15 else 0.0
        xE_sump = max(0.0, min(1.0, xE_sump))

        # 进料摩尔焓 (kJ/kmol)：进料为液相，按进料温度和组成计算
        h_F = liquid_enthalpy_kj_per_kmol(feed_xE, feed_temperature_k)

        # 塔板液相和气相摩尔焓 (kJ/kmol)
        h_L_tray = np.array([
            liquid_enthalpy_kj_per_kmol(float(xE_tray[i]), float(T_tray[i]))
            for i in range(n_trays)
        ], dtype=np.float64)
        h_V_tray = np.array([
            vapor_enthalpy_kj_per_kmol(float(yE_tray[i]), float(T_tray[i]))
            for i in range(n_trays)
        ], dtype=np.float64)

        # 回流罐和塔釜液相焓
        h_L_drum = liquid_enthalpy_kj_per_kmol(xE_drum, T_drum)
        h_L_sump = liquid_enthalpy_kj_per_kmol(xE_sump, T_sump)

        # 塔釜气相焓（蒸气离开塔釜进入塔底板）
        h_V_sump = vapor_enthalpy_kj_per_kmol(yE_sump, T_sump)
        # 塔顶板气相焓（蒸气离开塔顶板进入冷凝器/气相库存）
        h_V_top = h_V_tray[0]
        # 气相控制体内能/焓（按当前 yE_vapor, T_vapor）
        h_V_vapor = vapor_enthalpy_kj_per_kmol(yE_vapor, T_vapor)

        # ===== 阶段 2：Q_R → V_boil 真实机理（todo/5.md §5.2） =====
        # Q_R_available = (steam_flow_kg_h / 3600) * latent_heat * efficiency
        Q_R_available = (
            (steam_flow_kg_h / 3600.0)
            * self._steam_latent_heat_kj_per_kg
            * self._steam_heat_transfer_efficiency
        )  # kW

        # 塔釜泡点和气相组成
        try:
            T_bubble_sump, y_boil = bubble_point_temperature(float(xE_sump), float(p_sump))
        except (ValueError, RuntimeError):
            # 数值保护：求根失败时用当前 T_sump 作为近似
            T_bubble_sump = float(T_sump)
            y_boil = float(yE_sump)
        y_boil = max(0.0, min(1.0, float(y_boil)))

        # 散热损失
        Q_loss_sump = self._sump_ua * max(T_sump - T_amb, 0.0)  # kW

        # 显热升温（塔釜低于泡点时优先升温）
        cp_sump = liquid_heat_capacity_kj_per_kmol_k(float(xE_sump))
        # tau_sump_heat 用于限制显热升温速率
        Q_subcool_cap = (
            M_sump * cp_sump * max(T_bubble_sump - T_sump, 0.0)
            / self._tau_sump_heat_s
        )  # kW
        Q_subcool = min(max(Q_R_available - Q_loss_sump, 0.0), Q_subcool_cap)

        # 过热释放（塔釜高于泡点时释放显热帮助汽化）
        Q_superheat_release = (
            M_sump * cp_sump * max(T_sump - T_bubble_sump, 0.0)
            / self._tau_phase_s
        )  # kW

        # 用于汽化的热量
        Q_for_vaporization = max(
            0.0,
            Q_R_available - Q_loss_sump - Q_subcool + Q_superheat_release,
        )  # kW

        # V_boil = Q_for_vaporization / ΔH_vap_sump
        dh_vap_sump = max(heat_of_vaporization_kj_per_kmol(float(xE_sump)), 1.0)  # kJ/kmol
        V_boil_internal = Q_for_vaporization / dh_vap_sump  # kmol/s

        # 阶段 2 兼容路径：直接流量模式（spec §5.2 bypass）
        # 调用方显式传入 vapor_boilup 时，跳过 Q_R → V_boil 机理
        # 同时 Q_R_available 由反推得到（保持能量守恒）
        if direct_vapor_bypass is not None and direct_vapor_bypass >= 0.0:
            V_boil_internal = float(direct_vapor_bypass)
            # 反推 Q_R_available：Q_R = V_boil * ΔH_vap_sump + Q_loss_sump
            # 这样 dU_sump 中 +Q_R 与 -V_boil*h_V_sump 项的潜热部分抵消
            Q_R_available = V_boil_internal * dh_vap_sump + Q_loss_sump

        # 数值保护
        if not math.isfinite(V_boil_internal) or V_boil_internal < 0.0:
            V_boil_internal = 0.0
        # 限制 V_boil 不超过塔釜存量 / tau_phase_s（物理上不可能瞬间汽化全部塔釜）
        v_boil_cap = max(M_sump / self._tau_phase_s, 1e-9)
        if V_boil_internal > v_boil_cap:
            V_boil_internal = v_boil_cap

        # 用 y_boil 修正塔釜气相组成（用于塔釜气相流出的组分/焓）
        yE_sump_eff = y_boil
        h_V_sump_eff = vapor_enthalpy_kj_per_kmol(yE_sump_eff, T_bubble_sump)

        # ===== 阶段 2：Q_C → V_condense 真实机理（todo/5.md §6.3、§6.4） =====
        # 冷却水实际质量流量已由调用方转换为 kg/h
        # Q_flow = (m_cw / 3600) * Cp_cw * ΔT_cw_max
        Q_flow = (
            (cooling_flow_kg_h / 3600.0)
            * self._cooling_water_cp_kj_per_kg_k
            * self._cooling_water_design_delta_t_k
        )  # kW

        # Q_UA = UA * max(T_vapor - T_cw_in, 0)
        T_cw_in_k = float(cooling_water_temperature_c) + 273.15
        Q_UA = self._condenser_ua_kw_per_k * max(T_vapor - T_cw_in_k, 0.0)  # kW

        # Q_C_available = min(Q_flow, Q_UA)
        Q_C_available = min(Q_flow, Q_UA)  # kW

        # 冷凝单位摩尔需移除的热量 = h_v - h_l (T_condensate, yE_vapor)
        try:
            T_condensate, _ = bubble_point_temperature(float(yE_vapor), float(p_top))
        except (ValueError, RuntimeError):
            T_condensate = float(T_vapor)
        h_v_at_vapor = vapor_enthalpy_kj_per_kmol(float(yE_vapor), float(T_vapor))
        h_l_at_cond = liquid_enthalpy_kj_per_kmol(float(yE_vapor), float(T_condensate))
        delta_h_condense = max(h_v_at_vapor - h_l_at_cond, 1.0)  # kJ/kmol

        # V_condense_capacity = Q_C_available / delta_h_condense
        V_condense_capacity = Q_C_available / delta_h_condense  # kmol/s

        # 允许消耗气相库存（spec §6.4）
        # N_floor = P_VAPOR_FLOOR_KPA * V_gas / (R * T_vapor)
        N_floor = (
            self._p_vapor_floor_kpa * self._vapor_volume_m3
            / (R_UNIVERSAL_KPA_M3_PER_KMOL_K * max(T_vapor, 1.0))
        )
        inventory_release_capacity = max(N_vapor - N_floor, 0.0) / self._tau_condenser_inventory_s
        # vapor_available = V_top + inventory_release_capacity
        # V_top 是塔顶板离开进入气相库存的蒸气量
        # 阶段 3.1 修正：使用本周期 V_boil_internal（CMO 下 V_top = V_boil）
        # 而不是传入的上一周期 V，确保 RHS 内部塔板出口、气相入口、冷凝可用量一致
        vapor_available = V_boil_internal + inventory_release_capacity  # kmol/s

        # V_condense = min(V_condense_capacity, vapor_available)
        V_condense = min(V_condense_capacity, vapor_available)  # kmol/s
        if not math.isfinite(V_condense) or V_condense < 0.0:
            V_condense = 0.0

        # 实际冷凝负荷
        Q_C_actual = V_condense * delta_h_condense  # kW

        # 放空（第一版关闭）
        V_vent = max(0.0, float(self._vent_flow_kgmol_per_s))

        # 塔板导数
        dM = np.zeros(n_trays, dtype=np.float64)
        dnE = np.zeros(n_trays, dtype=np.float64)
        dU = np.zeros(n_trays, dtype=np.float64)

        for i in range(n_trays):
            # 上游液相
            if i == 0:
                L_in = reflux_flow
                xE_L_in = xE_drum
                h_L_in = h_L_drum
            else:
                L_in = L[i - 1]
                xE_L_in = xE_tray[i - 1]
                h_L_in = h_L_tray[i - 1]

            # 下游气相
            # 阶段 2：塔板底部气相来自塔釜 V_boil_internal（CMO 假设下 V_i = V_boil）
            if i == n_trays - 1:
                V_in = V_boil_internal
                yE_V_in = yE_sump_eff
                h_V_in = h_V_sump_eff
            else:
                V_in = V_boil_internal
                yE_V_in = yE_tray[i + 1]
                h_V_in = h_V_tray[i + 1]

            # 进料（仅进料板）
            F_i = feed_flow if i == feed_idx else 0.0

            # 总物料衡算（CMO：所有塔板 V_i = V_boil_internal）
            dM[i] = L_in + V_in + F_i - L[i] - V_boil_internal

            # 乙醇组分衡算
            dnE[i] = (
                L_in * xE_L_in
                + V_in * yE_V_in
                + F_i * feed_xE
                - L[i] * xE_tray[i]
                - V_boil_internal * yE_tray[i]
            )

            # 能量衡算 (kJ/s = kW)
            Q_loss = self._tray_ua * (T_tray[i] - T_amb)  # kW
            dU[i] = (
                L_in * h_L_in
                + V_in * h_V_in
                + F_i * h_F
                - L[i] * h_L_tray[i]
                - V_boil_internal * h_V_tray[i]
                - Q_loss
            )  # kJ/s = kW

        # ===== 阶段 2：回流罐入口使用 V_condense（todo/5.md §6.6） =====
        # dM_drum/dt = V_condense - R - D
        # dnE_drum/dt = V_condense * yE_vapor - (R+D) * xE_drum
        # dU_drum/dt = V_condense * h_L_cond - (R+D) * h_L_drum - Q_loss_drum
        # 回流罐入口液体焓使用冷凝液温度和 yE_vapor 组成
        Q_loss_drum = self._drum_ua * (T_drum - T_amb)
        h_L_cond = liquid_enthalpy_kj_per_kmol(float(yE_vapor), float(T_condensate))
        dM_drum = V_condense - reflux_flow - distillate_flow
        dnE_drum = V_condense * yE_vapor - (reflux_flow + distillate_flow) * xE_drum
        dU_drum = V_condense * h_L_cond - (reflux_flow + distillate_flow) * h_L_drum - Q_loss_drum

        # ===== 阶段 2：塔釜能量衡算使用实际 Q_R_available（todo/5.md §5.2） =====
        # dM_sump/dt = L[11] - B - V_boil
        # dnE_sump/dt = L[11]*xE[11] - B*xE_sump - V_boil*yE_sump_eff
        # dU_sump/dt = L[11]*h_L[11] - B*h_L_sump - V_boil*h_V_sump_eff - Q_loss_sump + Q_R_available
        dM_sump = L[n_trays - 1] - bottoms_flow - V_boil_internal
        dnE_sump = (
            L[n_trays - 1] * xE_tray[n_trays - 1]
            - bottoms_flow * xE_sump
            - V_boil_internal * yE_sump_eff
        )
        dU_sump = (
            L[n_trays - 1] * h_L_tray[n_trays - 1]
            - bottoms_flow * h_L_sump
            - V_boil_internal * h_V_sump_eff
            - Q_loss_sump
            + Q_R_available
        )

        # ===== 阶段 2：气相动态（todo/5.md §6.5） =====
        # dN_v/dt = V_top - V_condense - V_vent
        # dnE_v/dt = V_top * yE_top - V_condense * yE_vapor - V_vent * yE_vapor
        # dU_v/dt = V_top * h_V_top - V_condense * h_V_vapor - V_vent * h_V_vapor - Q_loss_vapor
        # 注意：spec §6.5 推荐"气相控制体流出按 vapor enthalpy，回流罐流入按 condensate liquid enthalpy"
        # 因此 dU_vapor 中冷凝流出按气相焓 h_V_vapor（不是液相焓 h_L_cond）
        # 冷凝器从气相带走的潜热通过气相→液相焓差计入总系统，避免重复扣除 Q_C
        # 阶段 3.1 修正：V_top 使用本周期 V_boil_internal（CMO 假设下 V_top = V_boil）
        # 不再使用传入的上一周期 V，消除 RHS 内部不一致
        Q_loss_vapor = 0.0  # 第一版气相控制体无散热（散热已在塔板/塔釜计入）
        dN_vapor = V_boil_internal - V_condense - V_vent
        dnE_vapor = V_boil_internal * yE_tray[0] - V_condense * yE_vapor - V_vent * yE_vapor
        dU_vapor = (
            V_boil_internal * h_V_top
            - V_condense * h_V_vapor
            - V_vent * h_V_vapor
            - Q_loss_vapor
        )

        # 保存再沸/冷凝负荷用于对外位号
        self._Q_R_kw = Q_R_available
        self._Q_C_kw = Q_C_actual
        # 内部 V_boil / V_condense 用于对外位号
        self._V_boil_internal = V_boil_internal
        self._V_condense_internal = V_condense

        return (dM, dnE, dU, dM_drum, dnE_drum, dU_drum,
                dM_sump, dnE_sump, dU_sump,
                dN_vapor, dnE_vapor, dU_vapor)

    # ------------------------------------------------------------------
    # 积分
    # ------------------------------------------------------------------
    def _integrate_substeps(
        self,
        feed_flow: float,
        feed_xE: float,
        feed_temperature_k: float,
        reflux_flow: float,
        distillate_flow: float,
        bottoms_flow: float,
        steam_flow_kg_h: float,
        cooling_flow_kg_h: float,
        cooling_water_temperature_c: float,
        direct_vapor_bypass: Optional[float] = None,
    ) -> None:
        """
        Heun/RK2 积分，内部子步。

        阶段 2 修改（todo/5.md §5、§6）：
        - 不再接收 vapor_boilup 作为驱动量，改为接收 steam_flow_kg_h 和 cooling_flow_kg_h
        - 气相状态 (nE_vapor, U_vapor) 参与积分
        - _calculate_rhs 新增气相动态 (dnE_vapor, dU_vapor)

        Args:
            direct_vapor_bypass: 直接流量模式下的 V_boil 旁路值（kmol/s）。
                None 表示阀位模式，使用 Q_R → V_boil 真实机理。
        """
        dt = self._internal_dt

        for _ in range(self._substeps):
            # ---- k1 = f(state) ----
            (T_tray, yE_tray, T_drum, T_sump, yE_sump, p_top, pressure_kpa, p_sump,
             T_vapor_avg, yE_vapor, T_vapor) = self._compute_algebraic(
                self._M_tray, self._nE_tray, self._U_tray,
                self._M_drum, self._nE_drum, self._U_drum,
                self._M_sump, self._nE_sump, self._U_sump,
                self._N_vapor, self._nE_vapor, self._U_vapor,
                # CMO 下 V 用于压降计算，用上一周期内部 V_boil 作为初值
                self._V_boil_internal,
            )
            # 保存代数量（用于守恒诊断和对外位号）
            self._T_tray = T_tray.copy()
            self._yE_tray = yE_tray.copy()
            self._T_drum = T_drum
            self._T_sump = T_sump
            self._yE_sump = yE_sump
            self._p_top_kpa = p_top
            self._pressure_kpa = pressure_kpa.copy()
            self._p_sump_kpa = p_sump
            self._T_vapor_avg = T_vapor_avg
            self._yE_vapor = yE_vapor
            self._T_vapor = T_vapor

            L = self._calculate_hydraulics(self._M_tray)

            (dM1, dnE1, dU1, dM_drum1, dnE_drum1, dU_drum1,
             dM_sump1, dnE_sump1, dU_sump1, dN_v1, dnE_v1, dU_v1) = self._calculate_rhs(
                self._M_tray, self._nE_tray, self._U_tray,
                self._M_drum, self._nE_drum, self._U_drum,
                self._M_sump, self._nE_sump, self._U_sump,
                self._N_vapor, self._nE_vapor, self._U_vapor,
                L, self._V_boil_internal,
                T_tray, yE_tray, T_drum, T_sump, yE_sump,
                T_vapor, yE_vapor, p_top, p_sump,
                feed_flow, feed_xE, feed_temperature_k,
                reflux_flow, distillate_flow, bottoms_flow,
                steam_flow_kg_h, cooling_flow_kg_h, cooling_water_temperature_c,
                direct_vapor_bypass=direct_vapor_bypass,
            )

            # ---- 预测步 ----
            M_pred = self._M_tray + dt * dM1
            nE_pred = self._nE_tray + dt * dnE1
            U_pred = self._U_tray + dt * dU1
            M_drum_pred = self._M_drum + dt * dM_drum1
            nE_drum_pred = self._nE_drum + dt * dnE_drum1
            U_drum_pred = self._U_drum + dt * dU_drum1
            M_sump_pred = self._M_sump + dt * dM_sump1
            nE_sump_pred = self._nE_sump + dt * dnE_sump1
            U_sump_pred = self._U_sump + dt * dU_sump1
            N_vapor_pred = self._N_vapor + dt * dN_v1
            nE_vapor_pred = self._nE_vapor + dt * dnE_v1
            U_vapor_pred = self._U_vapor + dt * dU_v1

            # 数值保护（spec §5.8：仅允许 1e-12 级截断）
            M_pred = np.maximum(M_pred, 1e-12)
            nE_pred = np.maximum(nE_pred, 0.0)
            nE_pred = np.minimum(nE_pred, M_pred)
            M_drum_pred = max(M_drum_pred, 1e-12)
            nE_drum_pred = max(nE_drum_pred, 0.0)
            nE_drum_pred = min(nE_drum_pred, M_drum_pred)
            M_sump_pred = max(M_sump_pred, 1e-12)
            nE_sump_pred = max(nE_sump_pred, 0.0)
            nE_sump_pred = min(nE_sump_pred, M_sump_pred)
            N_vapor_pred = max(N_vapor_pred, 1e-12)
            nE_vapor_pred = max(nE_vapor_pred, 0.0)
            nE_vapor_pred = min(nE_vapor_pred, N_vapor_pred)
            if not math.isfinite(U_vapor_pred):
                U_vapor_pred = self._U_vapor

            # ---- k2 = f(predicted) ----
            (T_tray_p, yE_tray_p, T_drum_p, T_sump_p, yE_sump_p, p_top_p, pressure_kpa_p,
             p_sump_p, T_vapor_avg_p, yE_vapor_p, T_vapor_p) = self._compute_algebraic(
                M_pred, nE_pred, U_pred,
                M_drum_pred, nE_drum_pred, U_drum_pred,
                M_sump_pred, nE_sump_pred, U_sump_pred,
                N_vapor_pred, nE_vapor_pred, U_vapor_pred,
                self._V_boil_internal,
            )
            L_pred = self._calculate_hydraulics(M_pred)

            (dM2, dnE2, dU2, dM_drum2, dnE_drum2, dU_drum2,
             dM_sump2, dnE_sump2, dU_sump2, dN_v2, dnE_v2, dU_v2) = self._calculate_rhs(
                M_pred, nE_pred, U_pred,
                M_drum_pred, nE_drum_pred, U_drum_pred,
                M_sump_pred, nE_sump_pred, U_sump_pred,
                N_vapor_pred, nE_vapor_pred, U_vapor_pred,
                L_pred, self._V_boil_internal,
                T_tray_p, yE_tray_p, T_drum_p, T_sump_p, yE_sump_p,
                T_vapor_p, yE_vapor_p, p_top_p, p_sump_p,
                feed_flow, feed_xE, feed_temperature_k,
                reflux_flow, distillate_flow, bottoms_flow,
                steam_flow_kg_h, cooling_flow_kg_h, cooling_water_temperature_c,
                direct_vapor_bypass=direct_vapor_bypass,
            )

            # ---- Heun 平均 ----
            self._M_tray = self._M_tray + dt * 0.5 * (dM1 + dM2)
            self._nE_tray = self._nE_tray + dt * 0.5 * (dnE1 + dnE2)
            self._U_tray = self._U_tray + dt * 0.5 * (dU1 + dU2)
            self._M_drum = self._M_drum + dt * 0.5 * (dM_drum1 + dM_drum2)
            self._nE_drum = self._nE_drum + dt * 0.5 * (dnE_drum1 + dnE_drum2)
            self._U_drum = self._U_drum + dt * 0.5 * (dU_drum1 + dU_drum2)
            self._M_sump = self._M_sump + dt * 0.5 * (dM_sump1 + dM_sump2)
            self._nE_sump = self._nE_sump + dt * 0.5 * (dnE_sump1 + dnE_sump2)
            self._U_sump = self._U_sump + dt * 0.5 * (dU_sump1 + dU_sump2)
            self._N_vapor = self._N_vapor + dt * 0.5 * (dN_v1 + dN_v2)
            self._nE_vapor = self._nE_vapor + dt * 0.5 * (dnE_v1 + dnE_v2)
            self._U_vapor = self._U_vapor + dt * 0.5 * (dU_v1 + dU_v2)

            # 数值保护
            self._M_tray = np.maximum(self._M_tray, 1e-12)
            self._nE_tray = np.maximum(self._nE_tray, 0.0)
            self._nE_tray = np.minimum(self._nE_tray, self._M_tray)
            self._M_drum = max(self._M_drum, 1e-12)
            self._nE_drum = max(self._nE_drum, 0.0)
            self._nE_drum = min(self._nE_drum, self._M_drum)
            self._M_sump = max(self._M_sump, 1e-12)
            self._nE_sump = max(self._nE_sump, 0.0)
            self._nE_sump = min(self._nE_sump, self._M_sump)
            self._N_vapor = max(self._N_vapor, 1e-12)
            self._nE_vapor = max(self._nE_vapor, 0.0)
            self._nE_vapor = min(self._nE_vapor, self._N_vapor)
            if not math.isfinite(self._U_vapor):
                # 数值保护：U_vapor 异常时用当前 T_vapor, yE_vapor 重建
                self._U_vapor = self._N_vapor * vapor_internal_energy_kj_per_kmol(
                    self._yE_vapor if hasattr(self, "_yE_vapor") else 0.5,
                    self._T_vapor if hasattr(self, "_T_vapor") else 350.0,
                )

        # 最终代数量更新
        (T_tray, yE_tray, T_drum, T_sump, yE_sump, p_top, pressure_kpa, p_sump,
         T_vapor_avg, yE_vapor, T_vapor) = self._compute_algebraic(
            self._M_tray, self._nE_tray, self._U_tray,
            self._M_drum, self._nE_drum, self._U_drum,
            self._M_sump, self._nE_sump, self._U_sump,
            self._N_vapor, self._nE_vapor, self._U_vapor,
            self._V_boil_internal,
        )
        # 最后再调用一次 RHS 以更新 Q_R、Q_C、V_boil_internal、V_condense_internal
        L_final = self._calculate_hydraulics(self._M_tray)
        self._calculate_rhs(
            self._M_tray, self._nE_tray, self._U_tray,
            self._M_drum, self._nE_drum, self._U_drum,
            self._M_sump, self._nE_sump, self._U_sump,
            self._N_vapor, self._nE_vapor, self._U_vapor,
            L_final, self._V_boil_internal,
            T_tray, yE_tray, T_drum, T_sump, yE_sump,
            T_vapor, yE_vapor, p_top, p_sump,
            feed_flow, feed_xE, feed_temperature_k,
            reflux_flow, distillate_flow, bottoms_flow,
            steam_flow_kg_h, cooling_flow_kg_h, cooling_water_temperature_c,
            direct_vapor_bypass=direct_vapor_bypass,
        )

        self._T_tray = T_tray.copy()
        self._yE_tray = yE_tray.copy()
        self._T_drum = T_drum
        self._T_sump = T_sump
        self._yE_sump = yE_sump
        self._p_top_kpa = p_top
        self._pressure_kpa = pressure_kpa.copy()
        self._p_sump_kpa = p_sump
        self._T_vapor_avg = T_vapor_avg
        self._yE_vapor = yE_vapor
        self._T_vapor = T_vapor
        # 更新 CMO 当前气相流量（用于守恒诊断和对外位号）
        self._V_kgmol_per_s = self._V_boil_internal

    # ------------------------------------------------------------------
    # 守恒诊断
    # ------------------------------------------------------------------
    def _calculate_balances_and_kpis(
        self,
        feed_flow: float,
        feed_xE: float,
        feed_temperature_k: float,
        reflux_flow: float,
        distillate_flow: float,
        bottoms_flow: float,
        vapor_boilup: float,
        dt: float,
    ) -> None:
        """
        计算守恒残差和积累率（todo/5.md §11）。

        阶段 2 修正：
        - U_total 包含 U_vapor（spec §11: 能量残差必须包含液相状态、气相 U_vapor）
        - 新增 accumulation 位号，区分积累率和闭合残差
        - mass_balance_residual_kg_h → 指向 closure residual
        - ethanol_balance_residual_kg_h → 指向 closure residual
        - energy_balance_residual_kw → 指向 closure residual

        瞬时积累率（动态过程不为 0）：
            mass_accumulation = F - D - B - V_vent·mw_vapor（kg/h）
            ethanol_accumulation = F·xE_F - D·xD - B·xB - V_vent·yE_vapor·MW_ethanol（kg/h）
            energy_accumulation = Q_R + F·h_F - Q_C - D·h_D - B·h_B - Q_loss（kW）

        闭合残差（理论上为 0，数值误差来源）：
            r_M = dM_inventory/dt - (F - D - B - V_vent)
            r_E = dnE_inventory/dt - (F·z_F - D·xD - B·xB - V_vent·yE_vapor)
            r_U = dU_inventory/dt - (Q_R + F·h_F - Q_C - D·h_D - B·h_B - Q_loss_total)
        """
        # 当前总存量（阶段 2 新增气相库存）
        M_total_kgmol = (
            float(np.sum(self._M_tray)) + self._M_drum + self._M_sump + self._N_vapor
        )
        nE_total_kgmol = (
            float(np.sum(self._nE_tray)) + self._nE_drum + self._nE_sump + self._nE_vapor
        )
        U_total_kj = (
            float(np.sum(self._U_tray)) + self._U_drum + self._U_sump + self._U_vapor
        )

        # 塔顶/塔底采出组成
        xD = self._nE_drum / self._M_drum if self._M_drum > 1e-15 else 0.0
        xD = max(0.0, min(1.0, xD))
        xB = self._nE_sump / self._M_sump if self._M_sump > 1e-15 else 0.0
        xB = max(0.0, min(1.0, xB))

        # 平均分子量
        mw_feed = _mixture_molecular_weight(feed_xE)
        mw_dist = _mixture_molecular_weight(xD)
        mw_bot = _mixture_molecular_weight(xB)
        mw_vapor = _mixture_molecular_weight(float(self._yE_vapor))

        # 放空流量（kmol/s）
        V_vent = max(0.0, float(self._vent_flow_kgmol_per_s))

        # 瞬时质量积累率 = F - D - B - V_vent（kg/h）
        feed_mass_kgh = feed_flow * mw_feed * 3600.0
        distillate_mass_kgh = distillate_flow * mw_dist * 3600.0
        bottoms_mass_kgh = bottoms_flow * mw_bot * 3600.0
        vent_mass_kgh = V_vent * mw_vapor * 3600.0
        self.mass_accumulation_kg_h = (
            feed_mass_kgh - distillate_mass_kgh - bottoms_mass_kgh - vent_mass_kgh
        )

        # 乙醇瞬时积累率（kg/h）
        feed_ethanol_kgh = feed_flow * feed_xE * MW_ETHANOL_KG_PER_KMOL * 3600.0
        distillate_ethanol_kgh = distillate_flow * xD * MW_ETHANOL_KG_PER_KMOL * 3600.0
        bottoms_ethanol_kgh = bottoms_flow * xB * MW_ETHANOL_KG_PER_KMOL * 3600.0
        vent_ethanol_kgh = V_vent * float(self._yE_vapor) * MW_ETHANOL_KG_PER_KMOL * 3600.0
        self.ethanol_accumulation_kg_h = (
            feed_ethanol_kgh - distillate_ethanol_kgh - bottoms_ethanol_kgh - vent_ethanol_kgh
        )

        # 能量守恒（kW）
        # 能量输入 = Q_R + F·h_F（进料带入）
        # 能量输出 = Q_C + D·h_D + B·h_B + Q_loss_total + V_vent·h_V_vapor
        h_F = liquid_enthalpy_kj_per_kmol(feed_xE, feed_temperature_k)  # kJ/kmol
        h_D = liquid_enthalpy_kj_per_kmol(xD, self._T_drum)             # kJ/kmol
        h_B = liquid_enthalpy_kj_per_kmol(xB, self._T_sump)             # kJ/kmol
        h_V_vapor = vapor_enthalpy_kj_per_kmol(float(self._yE_vapor), float(self._T_vapor))  # kJ/kmol

        Q_R = self._Q_R_kw  # kW
        Q_C = self._Q_C_kw  # kW

        # 总散热损失 (kW)
        T_amb = self._ambient_temperature_k
        Q_loss_total = (
            float(np.sum(self._tray_ua * (self._T_tray - T_amb)))
            + self._drum_ua * (self._T_drum - T_amb)
            + self._sump_ua * (self._T_sump - T_amb)
        )

        # 单位换算：流量 kmol/s × 焓 kJ/kmol = kJ/s = kW
        energy_in = Q_R + feed_flow * h_F                                          # kW
        energy_out = (
            Q_C
            + distillate_flow * h_D
            + bottoms_flow * h_B
            + V_vent * h_V_vapor
            + Q_loss_total
        )  # kW
        # 瞬时能量积累率（kW）
        self.energy_accumulation_kw = energy_in - energy_out

        # ===== 闭合残差（todo/5.md §11 + 阶段 3.2 修正）=====
        # spec §11: r_M = dM_inventory/dt - (F - D - B - V_vent)
        # 数值实现：用本期积累率近似 dM/dt，与上一期总存量比较
        # 由于 _calculate_balances_and_kpis 在积分后调用，当前 M_total 已更新
        # dM/dt 近似为 (M_total - M_total_prev) / dt
        # 但 spec 要求 r_M 应为 0（动态守恒），所以 r_M = accumulation - actual_dM/dt
        # 第一周期无法计算（无 prev），设为 0（阶段 3.2 修正：不再用 accumulation 冒充 residual）
        if self._first_execute:
            # 第一周期：无前态，闭合残差设为 0
            self.mass_closure_residual_kg_h = 0.0
            self.ethanol_closure_residual_kg_h = 0.0
            self.energy_closure_residual_kw = 0.0
        else:
            # 闭合残差 = 积累率 - (本期实际存量变化率)
            # 阶段 3.2 修正：真实总质量变化率必须用真实总质量计算
            # 不能用 delta_total_kmol * mw_feed（错误地用进料 MW 近似）
            # total_mass_kg = total_ethanol_kmol * MW_ETHANOL + (total_kmol - total_ethanol_kmol) * MW_WATER
            prev_total_mass_kg = (
                self._prev_nE_total_kgmol * MW_ETHANOL_KG_PER_KMOL
                + (self._prev_M_total_kgmol - self._prev_nE_total_kgmol) * MW_WATER_KG_PER_KMOL
            )
            curr_total_mass_kg = (
                nE_total_kgmol * MW_ETHANOL_KG_PER_KMOL
                + (M_total_kgmol - nE_total_kgmol) * MW_WATER_KG_PER_KMOL
            )
            actual_dM_kg_per_h = (curr_total_mass_kg - prev_total_mass_kg) / dt * 3600.0

            # 乙醇物质量变化率（kmol/s → kg/h），乙醇分子量恒定
            actual_dnE_kg_per_h = (
                (nE_total_kgmol - self._prev_nE_total_kgmol) / dt * MW_ETHANOL_KG_PER_KMOL * 3600.0
            )

            # 能量变化率（kJ/s = kW）
            actual_dU_kj_per_s = (U_total_kj - self._prev_U_total_kj) / dt

            # closure residual = accumulation - actual_d/dt
            # 注意符号约定：accumulation = in - out，actual_d/dt = (final - init)/dt
            # 稳态时两者都为 0；动态时应相等，残差为 0
            self.mass_closure_residual_kg_h = (
                self.mass_accumulation_kg_h - actual_dM_kg_per_h
            )
            self.ethanol_closure_residual_kg_h = (
                self.ethanol_accumulation_kg_h - actual_dnE_kg_per_h
            )
            self.energy_closure_residual_kw = (
                self.energy_accumulation_kw - actual_dU_kj_per_s
            )

        # 兼容位号：继续指向对应闭合残差（todo/5.md §11 + 阶段 3.2）
        self.mass_balance_residual_kg_h = self.mass_closure_residual_kg_h
        self.ethanol_balance_residual_kg_h = self.ethanol_closure_residual_kg_h
        self.energy_balance_residual_kw = self.energy_closure_residual_kw

        # 保存本期总存量供下期使用
        self._prev_M_total_kgmol = M_total_kgmol
        self._prev_nE_total_kgmol = nE_total_kgmol
        self._prev_U_total_kj = U_total_kj

        if self._first_execute:
            self._initial_total_mass = M_total_kgmol
            self._initial_total_ethanol = nE_total_kgmol
            self._initial_total_energy = U_total_kj
            self._cumulative_mass_in = 0.0
            self._cumulative_mass_out = 0.0
            self._cumulative_ethanol_in = 0.0
            self._cumulative_ethanol_out = 0.0
            self._cumulative_energy_in = 0.0
            self._cumulative_energy_out = 0.0
            self._first_execute = False
        else:
            self._cumulative_mass_in += feed_flow * mw_feed * dt
            self._cumulative_mass_out += (
                distillate_flow * mw_dist * dt + bottoms_flow * mw_bot * dt
            )
            self._cumulative_ethanol_in += (
                feed_flow * feed_xE * MW_ETHANOL_KG_PER_KMOL * dt
            )
            self._cumulative_ethanol_out += (
                distillate_flow * xD * MW_ETHANOL_KG_PER_KMOL * dt
                + bottoms_flow * xB * MW_ETHANOL_KG_PER_KMOL * dt
            )

    # ------------------------------------------------------------------
    # 发布对外位号
    # ------------------------------------------------------------------
    def _publish_scalar_attributes(self) -> None:
        """更新对外标量位号。"""
        # 塔板温度和组成
        for i in range(self._n_trays):
            setattr(self, f"stage_{i+1:02d}_temperature_c", float(self._T_tray[i] - 273.15))
            x_e = float(self._nE_tray[i] / self._M_tray[i]) if self._M_tray[i] > 1e-15 else 0.0
            x_e = max(0.0, min(1.0, x_e))
            setattr(self, f"stage_{i+1:02d}_ethanol_x", x_e)
            mw = _mixture_molecular_weight(x_e)
            setattr(self, f"stage_{i+1:02d}_liquid_holdup_kg", float(self._M_tray[i] * mw))

        # 塔顶塔底
        self.top_temperature_c = float(self._T_tray[0] - 273.15)
        self.bottom_temperature_c = float(self._T_sump - 273.15)
        self.top_pressure_kpa = float(self._p_top_kpa)
        self.bottom_pressure_kpa = float(self._p_sump_kpa)

        # 阶段 2 新增：灵敏板温度（spec §7.2）
        # sensitive_top = stage_03, sensitive_bottom = stage_10
        self.sensitive_top_temperature_c = float(self._T_tray[2] - 273.15)
        self.sensitive_bottom_temperature_c = float(self._T_tray[9] - 273.15)

        # 塔顶/塔底组成
        xD = self._nE_drum / self._M_drum if self._M_drum > 1e-15 else 0.0
        xD = max(0.0, min(1.0, xD))
        xB = self._nE_sump / self._M_sump if self._M_sump > 1e-15 else 0.0
        xB = max(0.0, min(1.0, xB))
        self.top_ethanol_x = xD
        self.bottom_ethanol_x = xB
        self.top_ethanol_wt = ethanol_mole_fraction_to_mass_fraction(xD)
        self.bottom_ethanol_wt = ethanol_mole_fraction_to_mass_fraction(xB)

        # 流量（kg/h）
        self.feed_flow_kg_h = _kgmols_to_kgh(
            self._last_feed_flow, _mixture_molecular_weight(
                ethanol_mass_fraction_to_mole_fraction(self._feed_ethanol_wt)
            )
        )
        self.reflux_flow_kg_h = _kgmols_to_kgh(
            self._last_reflux_flow, _mixture_molecular_weight(xD)
        )
        self.distillate_flow_kg_h = _kgmols_to_kgh(
            self._last_distillate_flow, _mixture_molecular_weight(xD)
        )
        self.bottoms_flow_kg_h = _kgmols_to_kgh(
            self._last_bottoms_flow, _mixture_molecular_weight(xB)
        )
        # 阶段 2：vapor_boilup_kg_h 使用内部 V_boil（不是外部输入）
        self.vapor_boilup_kg_h = _kgmols_to_kgh(
            float(self._V_boil_internal), _mixture_molecular_weight(float(self._yE_sump))
        )

        # 液位百分比（阶段 2 新增原始液位发布，spec §8.2）
        self.raw_reflux_drum_level_pct = float(self._M_drum / self._m_drum_max * 100.0)
        self.raw_reboiler_level_pct = float(self._M_sump / self._m_sump_max * 100.0)
        # 显示液位（钳制 [0, 100]，spec §8.2）
        self.reflux_drum_level_pct = float(
            max(0.0, min(100.0, self.raw_reflux_drum_level_pct))
        )
        self.reboiler_level_pct = float(
            max(0.0, min(100.0, self.raw_reboiler_level_pct))
        )

        # 阶段 C 新增：能量与压力位号
        self.reboiler_duty_kw = float(self._Q_R_kw) if math.isfinite(self._Q_R_kw) else 0.0
        self.condenser_duty_kw = float(self._Q_C_kw) if math.isfinite(self._Q_C_kw) else 0.0
        self.vapor_holdup_kgmol = float(self._N_vapor)
        self.ambient_temperature_c = float(self._ambient_temperature_k - 273.15)

        # 阶段 D 新增：六个阀门位号（spec §6.2 实际开度和流量必须对外暴露）
        for key, valve in self._valves.items():
            setattr(self, f"{key}_valve_command_pct", float(valve.command_pct))
            setattr(self, f"{key}_valve_actual_pct", float(valve.actual_pct))

        # 阶段 1 新增：公用工程质量流量和状态位号（todo/5.md §4.3）
        # 阶段 2：steam_flow_kg_h 和 cooling_flow_kg_h 已接入再沸/冷凝机理
        self.steam_flow_kg_h = float(self._last_steam_flow_kg_per_h)
        self.cooling_flow_kg_h = float(self._last_cooling_flow_kg_per_h)
        self.cooling_water_temperature_c = float(self._cooling_water_temperature_c)
        self.steam_supply_pressure_kpa = float(self._steam_supply_pressure_kpa)

        # 阶段 D 新增：分析仪位号（spec §6.3 真实值和仪表值分开）
        # 真实值就是 top_ethanol_wt / bottom_ethanol_wt
        self.top_ethanol_wt_true = float(self.top_ethanol_wt)
        self.bottom_ethanol_wt_true = float(self.bottom_ethanol_wt)
        # 分析仪读数（_analyzers 在 execute 中更新，这里只读取）
        self.top_ethanol_analyzer = float(self._analyzers["top"].output)
        self.bottom_ethanol_analyzer = float(self._analyzers["bottom"].output)

        # ===== 阶段 2 新增位号（todo/5.md §7.2、§11） =====
        # 实际冷凝量、内部 V_boil（避免与外部输入冲突）
        self.vapor_condense_kgmol_per_s = float(self._V_condense_internal)
        self.vapor_boilup_kgmol_per_s_internal = float(self._V_boil_internal)
        # 气相状态位号（spec §6.1）
        self.vapor_ethanol_y = float(self._yE_vapor)
        self.vapor_temperature_c = float(self._T_vapor - 273.15)
        # KPI 位号（spec §7.2）
        feed_ethanol_kgh = self.feed_flow_kg_h * self._feed_ethanol_wt
        distillate_ethanol_kgh = self.distillate_flow_kg_h * self.top_ethanol_wt
        if feed_ethanol_kgh > 1e-9:
            self.ethanol_recovery_pct = distillate_ethanol_kgh / feed_ethanol_kgh * 100.0
        else:
            self.ethanol_recovery_pct = 0.0
        # 合格产品流量（塔顶乙醇质量分数 ≥ 0.82 时为合格品）
        if self.top_ethanol_wt_true >= 0.82:
            self.qualified_product_flow_kg_h = float(self.distillate_flow_kg_h)
        else:
            self.qualified_product_flow_kg_h = 0.0
        # 比蒸汽消耗（kg 蒸汽 / kg 合格产品）
        if self.qualified_product_flow_kg_h > 1e-9:
            self.specific_steam_kg_per_kg_product = (
                float(self.steam_flow_kg_h) / self.qualified_product_flow_kg_h
            )
        else:
            self.specific_steam_kg_per_kg_product = 0.0

    # ------------------------------------------------------------------
    # 主执行
    # ------------------------------------------------------------------
    def execute(
        self,
        feed_flow_kgmol_per_s: Optional[float] = None,
        reflux_flow_kgmol_per_s: Optional[float] = None,
        distillate_flow_kgmol_per_s: Optional[float] = None,
        bottoms_flow_kgmol_per_s: Optional[float] = None,
        vapor_boilup_kgmol_per_s: Optional[float] = None,
        feed_ethanol_wt: Optional[float] = None,
        feed_temperature_c: Optional[float] = None,
        ambient_temperature_c: Optional[float] = None,
        feed_valve_pct: Optional[float] = None,
        reflux_valve_pct: Optional[float] = None,
        distillate_valve_pct: Optional[float] = None,
        bottoms_valve_pct: Optional[float] = None,
        steam_valve_pct: Optional[float] = None,
        cooling_valve_pct: Optional[float] = None,
        cooling_water_temperature_c: Optional[float] = None,
        steam_supply_pressure_kpa: Optional[float] = None,
        steam_flow_kg_h: Optional[float] = None,
        cooling_flow_kg_h: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        """
        执行一个周期的精馏塔动态计算。

        输入优先级（todo/5.md §4.4 + 修复指令 §6.3）：

        1. 传入任一 ``*_valve_pct``：进入阀位模式
           - 阀门命令更新，actual_pct 通过一阶响应演化
           - 实际流量 = valve_max_flow_kg_per_h × get_flow_fraction()
           - 过程阀质量流量按当前流股组成换算 kmol/s
           - 公用工程阀（steam/cooling）保持 kg/h
           - 同时传入的 *_flow_kgmol_per_s / steam_flow_kg_h / cooling_flow_kg_h 被忽略

        2. 不传任何 *_valve_pct：进入直接实际流量模式
           - 允许传入 F/R/D/B（kmol/s）和 steam_flow_kg_h/cooling_flow_kg_h
           - 这些流量直接进入 Q_R/Q_C 真实机理（与阀位模式共享植物方程）
           - 不传的字段保持上一周期值

        3. ``vapor_boilup_kgmol_per_s``（仅供遗留单元测试，todo/5.md §5.2 bypass）：
           - 显式传入时启用 direct_vapor_bypass，跳过 Q_R → V_boil 机理
           - 仅供阶段 B/C 测试复用，不得用于参考稳态生成
           - 不得用于正式 DSL
           - 不得用于模式等价性验证

        Args:
            feed_flow_kgmol_per_s: 进料摩尔流量 (kmol/s)，直接流量模式。
            reflux_flow_kgmol_per_s: 回流量 (kmol/s)。
            distillate_flow_kgmol_per_s: 塔顶采出 (kmol/s)。
            bottoms_flow_kgmol_per_s: 塔底采出 (kmol/s)。
            vapor_boilup_kgmol_per_s: 再沸蒸气量 (kmol/s)。仅供遗留测试 bypass 使用。
            feed_ethanol_wt: 进料乙醇质量分数。
            feed_temperature_c: 进料温度 (℃)。
            ambient_temperature_c: 环境温度 (℃)。
            feed_valve_pct: 进料阀命令开度 (0~100%)。
            reflux_valve_pct: 回流阀命令开度 (%)。
            distillate_valve_pct: 塔顶采出阀命令开度 (%)。
            bottoms_valve_pct: 塔底采出阀命令开度 (%)。
            steam_valve_pct: 蒸汽阀命令开度 (%)。
            cooling_valve_pct: 冷却水阀命令开度 (%)。
            cooling_water_temperature_c: 冷却水供入温度 (℃)。
            steam_supply_pressure_kpa: 蒸汽供入压力 (kPa(a))。
            steam_flow_kg_h: 直接实际公用工程蒸汽流量 (kg/h)，仅直接流量模式有效。
                与阀位模式共享 Q_R → V_boil 真实机理，不得与 vapor_boilup_kgmol_per_s 同时使用。
            cooling_flow_kg_h: 直接实际公用工程冷却水流量 (kg/h)，仅直接流量模式有效。
        """
        # 处理环境/进料参数
        if feed_ethanol_wt is not None:
            w = float(feed_ethanol_wt)
            if not (0.0 <= w <= 1.0):
                raise ValueError(f"feed_ethanol_wt 必须位于 [0, 1]，实际值={w!r}")
            self._feed_ethanol_wt = w
        if feed_temperature_c is not None:
            self._feed_temperature_c = float(feed_temperature_c)
        if ambient_temperature_c is not None:
            self._ambient_temperature_k = float(ambient_temperature_c) + 273.15
        # 阶段 1 新增：公用工程输入（仅持有状态，不影响再沸/冷凝）
        # 阶段 1.1 新增：执行与构造期相同的有限值/物理范围校验
        if cooling_water_temperature_c is not None:
            cwt = float(cooling_water_temperature_c)
            if not math.isfinite(cwt):
                raise ValueError(
                    f"cooling_water_temperature_c 必须为有限数值，实际值={cooling_water_temperature_c!r}"
                )
            if cwt <= -273.15:
                raise ValueError(
                    f"cooling_water_temperature_c 必须高于绝对零度 (-273.15 ℃)，实际值={cwt!r}"
                )
            self._cooling_water_temperature_c = cwt
        if steam_supply_pressure_kpa is not None:
            ssp = float(steam_supply_pressure_kpa)
            if not math.isfinite(ssp):
                raise ValueError(
                    f"steam_supply_pressure_kpa 必须为有限数值，实际值={steam_supply_pressure_kpa!r}"
                )
            if ssp <= 0.0:
                raise ValueError(
                    f"steam_supply_pressure_kpa 作为绝压必须严格大于0，实际值={ssp!r}"
                )
            self._steam_supply_pressure_kpa = ssp

        # 检查是否启用了阀位模式
        any_valve_input = any(
            v is not None for v in (
                feed_valve_pct, reflux_valve_pct, distillate_valve_pct,
                bottoms_valve_pct, steam_valve_pct, cooling_valve_pct,
            )
        )

        # 阶段 2 新增：direct_vapor_bypass 标志
        # 直接流量模式下若显式传入 vapor_boilup_kgmol_per_s，作为 bypass 传给 _integrate_substeps
        # 阀位模式下不使用 bypass，由 Q_R → V_boil 真实机理计算
        direct_vapor_bypass: Optional[float] = None

        if any_valve_input:
            # ===== 阀位模式：更新阀门命令并计算实际流量 =====
            self._valve_mode_enabled = True
            valve_inputs = {
                "feed": feed_valve_pct,
                "reflux": reflux_valve_pct,
                "distillate": distillate_valve_pct,
                "bottoms": bottoms_valve_pct,
                "steam": steam_valve_pct,
                "cooling": cooling_valve_pct,
            }
            for key, cmd in valve_inputs.items():
                if cmd is not None:
                    self._valves[key].set_command(float(cmd))

            # 阀门一阶响应更新（使用 cycle_time，与外部周期一致）
            for valve in self._valves.values():
                valve.update(self.cycle_time)

            # 阶段 1 修正：从阀门实际开度计算流量（todo/5.md §4.3）
            # 过程阀：质量流量 (kg/h) = 额定质量流量 × flow_fraction，再按流股组成换算 kmol/s
            # 公用工程阀：质量流量 (kg/h) = 额定质量流量 × flow_fraction，保持 kg/h 不转换
            feed_mass_kg_h = self._valve_max_flow_kg_per_h["feed"] * self._valves["feed"].get_flow_fraction()
            reflux_mass_kg_h = self._valve_max_flow_kg_per_h["reflux"] * self._valves["reflux"].get_flow_fraction()
            distillate_mass_kg_h = self._valve_max_flow_kg_per_h["distillate"] * self._valves["distillate"].get_flow_fraction()
            bottoms_mass_kg_h = self._valve_max_flow_kg_per_h["bottoms"] * self._valves["bottoms"].get_flow_fraction()
            self._last_steam_flow_kg_per_h = (
                self._valve_max_flow_kg_per_h["steam"] * self._valves["steam"].get_flow_fraction()
            )
            self._last_cooling_flow_kg_per_h = (
                self._valve_max_flow_kg_per_h["cooling"] * self._valves["cooling"].get_flow_fraction()
            )

            # 过程阀：质量流量 → kmol/s，使用当前流股组成对应的平均分子量
            # feed：用进料组成；reflux/distillate：用塔顶组成；bottoms：用塔底组成
            feed_mw = _mixture_molecular_weight(
                ethanol_mass_fraction_to_mole_fraction(self._feed_ethanol_wt)
            )
            # 塔顶组成（reflux 和 distillate 同组成）：
            # top_ethanol_wt 在 _publish_scalar_attributes 中更新，本周期可能尚未刷新
            # 使用上一周期的发布值（首次执行用初值）
            top_wt = float(self.top_ethanol_wt) if hasattr(self, "top_ethanol_wt") else 0.85
            bottom_wt = float(self.bottom_ethanol_wt) if hasattr(self, "bottom_ethanol_wt") else 0.015
            reflux_mw = _mixture_molecular_weight(ethanol_mass_fraction_to_mole_fraction(top_wt))
            distillate_mw = reflux_mw
            bottoms_mw = _mixture_molecular_weight(ethanol_mass_fraction_to_mole_fraction(bottom_wt))

            self._last_feed_flow = _kgh_to_kgmols(feed_mass_kg_h, feed_mw)
            self._last_reflux_flow = _kgh_to_kgmols(reflux_mass_kg_h, reflux_mw)
            self._last_distillate_flow = _kgh_to_kgmols(distillate_mass_kg_h, distillate_mw)
            self._last_bottoms_flow = _kgh_to_kgmols(bottoms_mass_kg_h, bottoms_mw)

            # 阶段 2：阀位模式下不再设置 _last_vapor_boilup
            # V_boil 由 _integrate_substeps 内部 Q_R → V_boil 真实机理计算
            # 保留 _last_vapor_boilup 字段用于守恒诊断（积分后由 _V_boil_internal 更新）
            # 阀位模式下 direct_vapor_bypass 保持 None
        else:
            # ===== 直接实际流量模式（修复指令 §6） =====
            # 与阀位模式共享 Q_R → V_boil / Q_C → V_condense 真实机理
            # 仅是"实际流量如何得到"不同：直接由调用方提供 vs 阀门特性反算
            if feed_flow_kgmol_per_s is not None:
                self._last_feed_flow = max(0.0, float(feed_flow_kgmol_per_s))
            if reflux_flow_kgmol_per_s is not None:
                self._last_reflux_flow = max(0.0, float(reflux_flow_kgmol_per_s))
            if distillate_flow_kgmol_per_s is not None:
                self._last_distillate_flow = max(0.0, float(distillate_flow_kgmol_per_s))
            if bottoms_flow_kgmol_per_s is not None:
                self._last_bottoms_flow = max(0.0, float(bottoms_flow_kgmol_per_s))

            # 直接实际公用工程流量输入（修复指令 §6.3）
            # 不在模型内部截断为阀门额定流量；非法输入应明确失败
            if steam_flow_kg_h is not None:
                value = float(steam_flow_kg_h)
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError(
                        f"steam_flow_kg_h 必须为非负有限数值，实际值={steam_flow_kg_h!r}"
                    )
                self._last_steam_flow_kg_per_h = value
            if cooling_flow_kg_h is not None:
                value = float(cooling_flow_kg_h)
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError(
                        f"cooling_flow_kg_h 必须为非负有限数值，实际值={cooling_flow_kg_h!r}"
                    )
                self._last_cooling_flow_kg_per_h = value

            if vapor_boilup_kgmol_per_s is not None:
                # 遗留测试 bypass（todo/5.md §5.2 + 修复指令 §6.4）：
                # 仅供阶段 B/C 单元测试复用；不得用于参考稳态生成、正式 DSL 或模式等价性验证
                if steam_flow_kg_h is not None:
                    raise ValueError(
                        "vapor_boilup_kgmol_per_s（测试 bypass）不得与 steam_flow_kg_h 同时使用："
                        "前者跳过 Q_R → V_boil 机理，后者走真实机理，二者语义冲突"
                    )
                self._last_vapor_boilup = max(0.0, float(vapor_boilup_kgmol_per_s))
                direct_vapor_bypass = self._last_vapor_boilup
            else:
                # 直接实际流量模式：保持 None，由 Q_R → V_boil 真实机理计算
                direct_vapor_bypass = None

            # 阀门仍按一阶响应演化（保持动态连续性）
            # 但实际流量由直接输入决定，阀门只是"跟随显示"
            if self._valve_mode_enabled:
                # 从直接流量模式切回阀位模式前的过渡：阀门继续演化
                for valve in self._valves.values():
                    valve.update(self.cycle_time)
            else:
                # 纯直接流量模式：阀门不演化，保持初始开度
                pass

        # 进料乙醇摩尔分数和温度（K）
        feed_xE = ethanol_mass_fraction_to_mole_fraction(self._feed_ethanol_wt)
        feed_temperature_k = self._feed_temperature_c + 273.15

        # 阶段 2 积分（todo/5.md §5、§6）
        # 阀位模式：steam/cooling 流量由阀门实际开度决定，Q_R → V_boil 真实机理
        # 直接流量模式：steam/cooling 保持上一周期值；若传 vapor_boilup 则作为 bypass
        self._integrate_substeps(
            feed_flow=self._last_feed_flow,
            feed_xE=feed_xE,
            feed_temperature_k=feed_temperature_k,
            reflux_flow=self._last_reflux_flow,
            distillate_flow=self._last_distillate_flow,
            bottoms_flow=self._last_bottoms_flow,
            steam_flow_kg_h=self._last_steam_flow_kg_per_h,
            cooling_flow_kg_h=self._last_cooling_flow_kg_per_h,
            cooling_water_temperature_c=self._cooling_water_temperature_c,
            direct_vapor_bypass=direct_vapor_bypass,
        )

        # 阶段 2：积分后 _last_vapor_boilup 用内部 V_boil 更新（守恒诊断用）
        self._last_vapor_boilup = float(self._V_boil_internal)

        # 守恒诊断
        self._calculate_balances_and_kpis(
            feed_flow=self._last_feed_flow,
            feed_xE=feed_xE,
            feed_temperature_k=feed_temperature_k,
            reflux_flow=self._last_reflux_flow,
            distillate_flow=self._last_distillate_flow,
            bottoms_flow=self._last_bottoms_flow,
            vapor_boilup=self._last_vapor_boilup,
            dt=self.cycle_time,
        )

        # 阶段 D：更新浓度分析仪（使用当前真实值）
        self._analyzers["top"].update(self.top_ethanol_wt, self.cycle_time)
        self._analyzers["bottom"].update(self.bottom_ethanol_wt, self.cycle_time)

        # 发布对外位号
        self._publish_scalar_attributes()

        # 物理边界检查
        self._check_physical_bounds()

    # ------------------------------------------------------------------
    # 物理边界检查
    # ------------------------------------------------------------------
    def _check_physical_bounds(self) -> None:
        """
        检查状态是否在物理合理范围，明显越界抛异常（spec §8.1）。

        spec §8.1 强制约束：
            M <= 0                     → error
            nE < -1e-12                → error
            nE > M + 1e-12             → error
            N_vapor <= 0               → error
            nE_vapor < -1e-12          → error
            nE_vapor > N_vapor + 1e-12 → error
            温度不在 250～500 K         → error
            压力不在 50～160 kPa(a)    → error
            任意状态 NaN/Inf            → error

        只允许修正绝对值不超过 1e-12 的浮点越界（spec §8.1）。
        """
        # 检查塔板状态
        for i in range(self._n_trays):
            if not math.isfinite(float(self._M_tray[i])):
                raise RuntimeError(f"塔板 {i+1} 持液量非有限: {self._M_tray[i]}")
            if not math.isfinite(float(self._nE_tray[i])):
                raise RuntimeError(f"塔板 {i+1} 乙醇物质量非有限: {self._nE_tray[i]}")
            if not math.isfinite(float(self._U_tray[i])):
                raise RuntimeError(f"塔板 {i+1} 内能非有限: {self._U_tray[i]}")
            if self._M_tray[i] <= 0.0:
                raise RuntimeError(f"塔板 {i+1} 持液量非正: {self._M_tray[i]}")
            # spec §8.1: nE 容差 -1e-12 ~ M + 1e-12
            if self._nE_tray[i] < -1e-12 or self._nE_tray[i] > self._M_tray[i] + 1e-12:
                raise RuntimeError(
                    f"塔板 {i+1} 乙醇物质量越界: nE={self._nE_tray[i]}, M={self._M_tray[i]}"
                )
            if not math.isfinite(float(self._T_tray[i])):
                raise RuntimeError(f"塔板 {i+1} 温度非有限: {self._T_tray[i]}")
            if self._T_tray[i] < 250.0 or self._T_tray[i] > 500.0:
                raise RuntimeError(
                    f"塔板 {i+1} 温度超出合理范围: {self._T_tray[i]} K"
                )
            # spec §8.1: 压力范围 50～160 kPa(a)
            if not math.isfinite(float(self._pressure_kpa[i])) or self._pressure_kpa[i] <= 0.0:
                raise RuntimeError(
                    f"塔板 {i+1} 压力异常: {self._pressure_kpa[i]}"
                )
            if self._pressure_kpa[i] < 50.0 or self._pressure_kpa[i] > 160.0:
                raise RuntimeError(
                    f"塔板 {i+1} 压力超出合理范围 [50, 160] kPa(a): {self._pressure_kpa[i]}"
                )

        # 检查回流罐和塔釜
        for name, M, nE, U in [
            ("回流罐", self._M_drum, self._nE_drum, self._U_drum),
            ("塔釜", self._M_sump, self._nE_sump, self._U_sump),
        ]:
            if not math.isfinite(float(M)) or M <= 0.0:
                raise RuntimeError(f"{name} 持液量异常: {M}")
            # spec §8.1: nE 容差 -1e-12 ~ M + 1e-12
            if not math.isfinite(float(nE)) or nE < -1e-12 or nE > M + 1e-12:
                raise RuntimeError(f"{name} 乙醇物质量越界: nE={nE}, M={M}")
            if not math.isfinite(float(U)):
                raise RuntimeError(f"{name} 内能非有限: {U}")

        # 检查气相存量（spec §8.1: N_vapor > 0, nE_vapor 容差, U_vapor 有限）
        if not math.isfinite(float(self._N_vapor)) or self._N_vapor <= 0.0:
            raise RuntimeError(f"气相存量异常: {self._N_vapor}")
        if not math.isfinite(float(self._nE_vapor)):
            raise RuntimeError(f"气相乙醇物质量非有限: {self._nE_vapor}")
        # spec §8.1: nE_vapor 容差 -1e-12 ~ N_vapor + 1e-12
        if self._nE_vapor < -1e-12 or self._nE_vapor > self._N_vapor + 1e-12:
            raise RuntimeError(
                f"气相乙醇物质量越界: nE_vapor={self._nE_vapor}, N_vapor={self._N_vapor}"
            )
        if not math.isfinite(float(self._U_vapor)):
            raise RuntimeError(f"气相内能非有限: {self._U_vapor}")

        # 检查塔顶压力（spec §8.1: 50～160 kPa(a)）
        if not math.isfinite(float(self._p_top_kpa)) or self._p_top_kpa <= 0.0:
            raise RuntimeError(f"塔顶压力异常: {self._p_top_kpa}")
        if self._p_top_kpa < 50.0 or self._p_top_kpa > 160.0:
            raise RuntimeError(
                f"塔顶压力超出合理范围 [50, 160] kPa(a): {self._p_top_kpa}"
            )

        # 检查塔釜压力（spec §8.1: 50～160 kPa(a)）
        if not math.isfinite(float(self._p_sump_kpa)) or self._p_sump_kpa <= 0.0:
            raise RuntimeError(f"塔釜压力异常: {self._p_sump_kpa}")
        if self._p_sump_kpa < 50.0 or self._p_sump_kpa > 160.0:
            raise RuntimeError(
                f"塔釜压力超出合理范围 [50, 160] kPa(a): {self._p_sump_kpa}"
            )

    # ==================================================================
    # 阶段 D：状态持久化（spec §10.1, §10.2）
    # ==================================================================

    # 参考稳态文件版本号（变更状态结构时升版）
    # 阶段 2 升版 "1.0" → "2.0"：新增 nE_vapor, U_vapor, yE_vapor, T_vapor,
    # V_boil_internal, V_condense_internal, prev_M_total_kgmol 等状态字段
    REFERENCE_STATE_VERSION: str = "2.0"

    # 关键设备参数（用于参数哈希，决定稳态文件是否可复用）
    _PARAMS_HASH_KEYS = (
        "tray_count", "feed_stage",
        "top_pressure_kpa", "pressure_drop_per_stage_kpa",
        "pressure_drop_kv_kpa_s2_per_kgmol2",
        "m_tray_nom_kmol", "m_drum_nom_kmol", "m_sump_nom_kmol",
        "m_drum_max_kmol", "m_sump_max_kmol",
        "feed_flow_kgmol_per_s", "distillate_flow_kgmol_per_s",
        "bottoms_flow_kgmol_per_s", "reflux_flow_kgmol_per_s",
        "vapor_boilup_kgmol_per_s",
        "feed_ethanol_wt", "feed_temperature_c",
        "vapor_volume_m3",
        # 阶段 1：使用额定质量流量（todo/5.md §4.2）
        "feed_valve_max_flow_kg_per_h",
        "reflux_valve_max_flow_kg_per_h",
        "distillate_valve_max_flow_kg_per_h",
        "bottoms_valve_max_flow_kg_per_h",
        "steam_valve_max_flow_kg_per_h",
        "cooling_valve_max_flow_kg_per_h",
        # 阶段 2：再沸器/冷凝器/气相库存关键参数（todo/5.md §5, §6）
        # 修改这些参数会改变稳态形状，必须重新生成参考状态
        "steam_latent_heat_kj_per_kg",
        "steam_heat_transfer_efficiency",
        "cooling_water_cp_kj_per_kg_k",
        "cooling_water_design_delta_t_k",
        "condenser_ua_kw_per_k",
        "p_vapor_floor_kpa",
        "tau_condenser_inventory_s",
        "tau_sump_heat_s",
        "tau_phase_s",
        "vent_flow_kgmol_per_s",
    )

    def _compute_params_hash(self) -> str:
        """
        计算关键设备参数的哈希值。

        spec §10.1: 用户修改关键设备参数后，旧稳态不得静默复用。
        哈希包括塔结构、压力、持液量、流量、阀门最大流量等。
        不包括随机种子、环境温度、分析仪参数（不影响稳态形状）。

        使用 __init__ 时的快照（_params_hash_snapshot），避免运行时
        被覆盖的动态输出（如 top_pressure_kpa）影响哈希。
        """
        import hashlib
        import json
        # 优先使用 __init__ 快照；若尚未创建（如构造期间调用），回退到当前属性
        if hasattr(self, "_params_hash_snapshot") and self._params_hash_snapshot:
            params = dict(self._params_hash_snapshot)
        else:
            params = {key: getattr(self, key) for key in self._PARAMS_HASH_KEYS}
        # 序列化为规范化 JSON（按 key 排序）
        json_str = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    def _get_full_state_dict(self) -> dict:
        """导出完整状态用于持久化。"""
        return {
            "version": self.REFERENCE_STATE_VERSION,
            "params_hash": self._compute_params_hash(),
            # 塔板液相状态
            "M_tray": self._M_tray.tolist(),
            "nE_tray": self._nE_tray.tolist(),
            "U_tray": self._U_tray.tolist(),
            # 回流罐
            "M_drum": float(self._M_drum),
            "nE_drum": float(self._nE_drum),
            "U_drum": float(self._U_drum),
            # 塔釜
            "M_sump": float(self._M_sump),
            "nE_sump": float(self._nE_sump),
            "U_sump": float(self._U_sump),
            # 气相存量（阶段 2: 新增 nE_vapor, U_vapor）
            "N_vapor": float(self._N_vapor),
            "nE_vapor": float(self._nE_vapor),
            "U_vapor": float(self._U_vapor),
            # 派生量（避免重新计算）
            "T_tray": self._T_tray.tolist(),
            "yE_tray": self._yE_tray.tolist(),
            "pressure_kpa": self._pressure_kpa.tolist(),
            "T_drum": float(self._T_drum),
            "T_sump": float(self._T_sump),
            "yE_sump": float(self._yE_sump),
            "p_top_kpa": float(self._p_top_kpa),
            "p_sump_kpa": float(self._p_sump_kpa),
            "T_vapor_avg": float(self._T_vapor_avg),
            # 阶段 2: 气相组成和温度（派生量，避免加载后 _publish_scalar_attributes 报错）
            "yE_vapor": float(self._yE_vapor),
            "T_vapor": float(self._T_vapor),
            # 阶段 2: 内部 V_boil/V_condense（用于诊断位号恢复）
            "V_boil_internal": float(self._V_boil_internal),
            "V_condense_internal": float(self._V_condense_internal),
            # 阶段 C 内部热负荷（用于对外位号恢复）
            "Q_R_kw": float(self._Q_R_kw),
            "Q_C_kw": float(self._Q_C_kw),
            # 阶段 C 累计能量（守恒诊断用）
            "cumulative_energy_in": float(self._cumulative_energy_in),
            "cumulative_energy_out": float(self._cumulative_energy_out),
            "initial_total_energy": float(self._initial_total_energy),
            # 阶段 D V_kgmol_per_s（CMO 当前气相流量）
            "V_kgmol_per_s": float(self._V_kgmol_per_s),
            # 阶段 D 阀位模式标志
            "valve_mode_enabled": bool(self._valve_mode_enabled),
            # 对外诊断残差（_publish_scalar_attributes 不重新计算这些）
            "mass_balance_residual_kg_h": float(self.mass_balance_residual_kg_h),
            "ethanol_balance_residual_kg_h": float(self.ethanol_balance_residual_kg_h),
            "energy_balance_residual_kw": float(self.energy_balance_residual_kw),
            # 阶段 3.2: 明确闭合残差位号
            "mass_closure_residual_kg_h": float(self.mass_closure_residual_kg_h),
            "ethanol_closure_residual_kg_h": float(self.ethanol_closure_residual_kg_h),
            "energy_closure_residual_kw": float(self.energy_closure_residual_kw),
            # 阶段 2: 积累率位号（_publish_scalar_attributes 不重新计算这些）
            "mass_accumulation_kg_h": float(self.mass_accumulation_kg_h),
            "ethanol_accumulation_kg_h": float(self.ethanol_accumulation_kg_h),
            "energy_accumulation_kw": float(self.energy_accumulation_kw),
            # 阀门状态
            "valves": {k: v.to_state_dict() for k, v in self._valves.items()},
            # 分析仪状态
            "analyzers": {k: a.to_state_dict() for k, a in self._analyzers.items()},
            # 工况参数
            "feed_ethanol_wt": float(self._feed_ethanol_wt),
            "feed_temperature_c": float(self._feed_temperature_c),
            "ambient_temperature_k": float(self._ambient_temperature_k),
            "last_feed_flow": float(self._last_feed_flow),
            "last_reflux_flow": float(self._last_reflux_flow),
            "last_distillate_flow": float(self._last_distillate_flow),
            "last_bottoms_flow": float(self._last_bottoms_flow),
            "last_vapor_boilup": float(self._last_vapor_boilup),
            # 阶段 1：公用工程状态（todo/5.md §3.2）
            "cooling_water_temperature_c": float(self._cooling_water_temperature_c),
            "steam_supply_pressure_kpa": float(self._steam_supply_pressure_kpa),
            "last_steam_flow_kg_per_h": float(self._last_steam_flow_kg_per_h),
            "last_cooling_flow_kg_per_h": float(self._last_cooling_flow_kg_per_h),
            # 守恒诊断累计
            "cumulative": {
                "mass_in": self._cumulative_mass_in,
                "mass_out": self._cumulative_mass_out,
                "ethanol_in": self._cumulative_ethanol_in,
                "ethanol_out": self._cumulative_ethanol_out,
            },
            "initial_total_mass": self._initial_total_mass,
            "initial_total_ethanol": self._initial_total_ethanol,
            "first_execute": self._first_execute,
            # 阶段 2: 闭合残差计算所需的上一期总存量（save→load 后保持一致）
            "prev_M_total_kgmol": float(self._prev_M_total_kgmol),
            "prev_nE_total_kgmol": float(self._prev_nE_total_kgmol),
            "prev_U_total_kj": float(self._prev_U_total_kj),
        }

    # ------------------------------------------------------------------
    def _set_full_state_dict(self, state: dict) -> None:
        """从 dict 恢复完整状态。"""
        # 版本校验
        if state["version"] != self.REFERENCE_STATE_VERSION:
            raise ValueError(
                f"参考稳态文件版本不匹配: 文件={state['version']}, "
                f"当前={self.REFERENCE_STATE_VERSION}"
            )

        # 参数哈希校验（spec §10.1: 修改参数后不得静默复用）
        current_hash = self._compute_params_hash()
        if state["params_hash"] != current_hash:
            raise ValueError(
                f"参考稳态文件参数哈希不匹配: 文件={state['params_hash']}, "
                f"当前={current_hash}。用户修改了关键设备参数，必须重新生成稳态。"
            )

        # 恢复塔板状态
        self._M_tray = np.array(state["M_tray"], dtype=np.float64)
        self._nE_tray = np.array(state["nE_tray"], dtype=np.float64)
        self._U_tray = np.array(state["U_tray"], dtype=np.float64)
        self._M_drum = float(state["M_drum"])
        self._nE_drum = float(state["nE_drum"])
        self._U_drum = float(state["U_drum"])
        self._M_sump = float(state["M_sump"])
        self._nE_sump = float(state["nE_sump"])
        self._U_sump = float(state["U_sump"])
        self._N_vapor = float(state["N_vapor"])
        # 阶段 2: 恢复 nE_vapor, U_vapor（向后兼容：旧版无此键时由 N_vapor 推算）
        # 注：REFERENCE_STATE_VERSION 升版后旧文件不会加载，此 .get() 仅作安全网
        self._nE_vapor = float(state.get("nE_vapor", 0.0))
        self._U_vapor = float(state.get("U_vapor", 0.0))
        # 若缺失，用 N_vapor 和塔顶 yE 推算合理初值
        if self._nE_vapor <= 0.0 and self._N_vapor > 0.0:
            yE_init = 0.5
            self._nE_vapor = float(self._N_vapor * yE_init)
        if self._U_vapor <= 0.0 and self._N_vapor > 0.0:
            yE_init = float(self._nE_vapor / self._N_vapor) if self._N_vapor > 0 else 0.5
            T_init = 350.0
            self._U_vapor = float(
                self._N_vapor * vapor_internal_energy_kj_per_kmol(yE_init, T_init)
            )

        # 恢复派生量
        self._T_tray = np.array(state["T_tray"], dtype=np.float64)
        self._yE_tray = np.array(state["yE_tray"], dtype=np.float64)
        self._pressure_kpa = np.array(state["pressure_kpa"], dtype=np.float64)
        self._T_drum = float(state["T_drum"])
        self._T_sump = float(state["T_sump"])
        self._yE_sump = float(state["yE_sump"])
        self._p_top_kpa = float(state["p_top_kpa"])
        self._p_sump_kpa = float(state["p_sump_kpa"])
        self._T_vapor_avg = float(state["T_vapor_avg"])
        # 阶段 2: 恢复气相组成和温度（向后兼容：缺失时从 N_vapor/nE_vapor/U_vapor 反算）
        if "yE_vapor" in state:
            self._yE_vapor = float(state["yE_vapor"])
        else:
            self._yE_vapor = (
                float(self._nE_vapor / self._N_vapor)
                if self._N_vapor > 0 else 0.5
            )
        if "T_vapor" in state:
            self._T_vapor = float(state["T_vapor"])
        else:
            self._T_vapor = float(
                temperature_from_vapor_internal_energy(
                    self._U_vapor, self._N_vapor, self._yE_vapor
                )
            )
        # 阶段 2: 恢复内部 V_boil/V_condense（向后兼容：缺失时用 0，下次 execute 会重算）
        self._V_boil_internal = float(state.get("V_boil_internal", 0.0))
        self._V_condense_internal = float(state.get("V_condense_internal", 0.0))

        # 恢复内部热负荷（向后兼容：旧版无此键时保持 0）
        self._Q_R_kw = float(state.get("Q_R_kw", 0.0))
        self._Q_C_kw = float(state.get("Q_C_kw", 0.0))

        # 恢复累计能量诊断（向后兼容：旧版无此键时保持 0）
        self._cumulative_energy_in = float(state.get("cumulative_energy_in", 0.0))
        self._cumulative_energy_out = float(state.get("cumulative_energy_out", 0.0))
        self._initial_total_energy = float(state.get("initial_total_energy", 0.0))

        # 恢复 V_kgmol_per_s 和阀位模式标志（向后兼容）
        # 注意：不能用 self._last_vapor_boilup 作为默认值，因为 STEADY 模式 __init__
        # 调用 _set_full_state_dict 时该属性尚未初始化（它在后面才从 state["last_vapor_boilup"]
        # 恢复）。改用 state["last_vapor_boilup"] 作为回退，避免 AttributeError。
        self._V_kgmol_per_s = float(state.get("V_kgmol_per_s", state.get("last_vapor_boilup", 0.0)))
        self._valve_mode_enabled = bool(state.get("valve_mode_enabled", False))

        # 恢复对外诊断残差（_publish_scalar_attributes 不重新计算这些）
        self.mass_balance_residual_kg_h = float(state.get("mass_balance_residual_kg_h", 0.0))
        self.ethanol_balance_residual_kg_h = float(state.get("ethanol_balance_residual_kg_h", 0.0))
        self.energy_balance_residual_kw = float(state.get("energy_balance_residual_kw", 0.0))
        # 阶段 3.2: 恢复明确闭合残差位号（向后兼容）
        self.mass_closure_residual_kg_h = float(state.get("mass_closure_residual_kg_h", self.mass_balance_residual_kg_h))
        self.ethanol_closure_residual_kg_h = float(state.get("ethanol_closure_residual_kg_h", self.ethanol_balance_residual_kg_h))
        self.energy_closure_residual_kw = float(state.get("energy_closure_residual_kw", self.energy_balance_residual_kw))
        # 阶段 2: 恢复积累率位号（_publish_scalar_attributes 不重新计算这些）
        self.mass_accumulation_kg_h = float(state.get("mass_accumulation_kg_h", 0.0))
        self.ethanol_accumulation_kg_h = float(state.get("ethanol_accumulation_kg_h", 0.0))
        self.energy_accumulation_kw = float(state.get("energy_accumulation_kw", 0.0))

        # 恢复阀门
        # 注意：STEADY 模式 __init__ 调用 _set_full_state_dict 时 _valves 尚未创建
        # （它在 __init__ 后段才创建）。此时跳过阀门状态恢复，阀门将在 __init__ 后段
        # 用基于已加载状态计算的初始开度创建。运行时 load_state() 路径下 _valves 已存在，
        # 正常恢复。
        if hasattr(self, "_valves") and "valves" in state:
            for k, v_state in state["valves"].items():
                if k in self._valves:
                    self._valves[k].load_state_dict(v_state)

        # 恢复分析仪（同上：STEADY __init__ 路径下 _analyzers 尚未创建时跳过）
        if hasattr(self, "_analyzers") and "analyzers" in state:
            for k, a_state in state["analyzers"].items():
                if k in self._analyzers:
                    self._analyzers[k].load_state_dict(a_state)

        # 恢复工况参数
        self._feed_ethanol_wt = float(state["feed_ethanol_wt"])
        self._feed_temperature_c = float(state["feed_temperature_c"])
        self._ambient_temperature_k = float(state["ambient_temperature_k"])
        self._last_feed_flow = float(state["last_feed_flow"])
        self._last_reflux_flow = float(state["last_reflux_flow"])
        self._last_distillate_flow = float(state["last_distillate_flow"])
        self._last_bottoms_flow = float(state["last_bottoms_flow"])
        self._last_vapor_boilup = float(state["last_vapor_boilup"])

        # 阶段 1：恢复公用工程状态（向后兼容：旧版无此键时使用 __init__ 值）
        # 注意：用 getattr(self, "_xxx", default) 而非 self._xxx 作为 .get() 默认值，
        # 因为 STEADY 模式 __init__ 调用 _set_full_state_dict 时这些属性尚未初始化
        # （Python 会先求值 .get() 的默认参数，导致 AttributeError）。
        # STEADY 路径下这些值会在 __init__ 后段被覆盖，这里仅运行时 load_state() 路径需要回退。
        self._cooling_water_temperature_c = float(
            state.get("cooling_water_temperature_c", getattr(self, "_cooling_water_temperature_c", 25.0))
        )
        self._steam_supply_pressure_kpa = float(
            state.get("steam_supply_pressure_kpa", getattr(self, "_steam_supply_pressure_kpa", 300.0))
        )
        self._last_steam_flow_kg_per_h = float(
            state.get("last_steam_flow_kg_per_h", getattr(self, "_last_steam_flow_kg_per_h", 0.0))
        )
        self._last_cooling_flow_kg_per_h = float(
            state.get("last_cooling_flow_kg_per_h", getattr(self, "_last_cooling_flow_kg_per_h", 0.0))
        )

        # 恢复守恒诊断累计
        self._cumulative_mass_in = float(state["cumulative"]["mass_in"])
        self._cumulative_mass_out = float(state["cumulative"]["mass_out"])
        self._cumulative_ethanol_in = float(state["cumulative"]["ethanol_in"])
        self._cumulative_ethanol_out = float(state["cumulative"]["ethanol_out"])
        self._initial_total_mass = float(state["initial_total_mass"])
        self._initial_total_ethanol = float(state["initial_total_ethanol"])
        self._first_execute = bool(state["first_execute"])
        # 阶段 2: 恢复上一期总存量（向后兼容：缺失时设为 0，下期残差按 first_execute 处理）
        self._prev_M_total_kgmol = float(state.get("prev_M_total_kgmol", 0.0))
        self._prev_nE_total_kgmol = float(state.get("prev_nE_total_kgmol", 0.0))
        self._prev_U_total_kj = float(state.get("prev_U_total_kj", 0.0))

    # ------------------------------------------------------------------
    def save_reference_state(self, file_path: Optional[str] = None) -> str:
        """
        保存当前状态为参考稳态文件（spec §10.1）。

        Args:
            file_path: 目标文件路径。None 时使用 default_params 中的 reference_state_file。

        Returns:
            实际保存的绝对路径。
        """
        import json
        import os

        if file_path is None:
            file_path = str(self.reference_state_file)

        # 转为绝对路径（相对于项目根目录）
        if not os.path.isabs(file_path):
            # 找到 review3 项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            file_path = os.path.join(project_root, file_path)

        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        state = self._get_full_state_dict()
        # 附加元数据
        state["metadata"] = {
            "created_at": "auto-generated",
            "description": "Ethanol-water distillation reference steady state",
            "model_name": "ETHANOL_WATER_DISTILLATION",
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        self._reference_state_path = file_path
        self._reference_state_saved = True
        logger.info(f"参考稳态已保存到: {file_path}")
        return file_path

    # ------------------------------------------------------------------
    def load_reference_state(self, file_path: Optional[str] = None) -> bool:
        """
        从参考稳态文件加载状态（spec §10.1）。

        Args:
            file_path: 源文件路径。None 时使用 default_params 中的 reference_state_file。

        Returns:
            True 加载成功；False 文件不存在或哈希不匹配（保持现有初始化）。

        Raises:
            ValueError: 文件存在但版本不匹配（明确报错而非静默忽略）。
        """
        import json
        import os

        if file_path is None:
            file_path = str(self.reference_state_file)

        # 转为绝对路径
        if not os.path.isabs(file_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            file_path = os.path.join(project_root, file_path)

        if not os.path.exists(file_path):
            logger.info(f"参考稳态文件不存在，使用默认初始化: {file_path}")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"参考稳态文件读取失败: {e}，使用默认初始化")
            return False

        try:
            self._set_full_state_dict(state)
        except ValueError as e:
            # 参数哈希不匹配：不允许静默复用（spec §10.1）
            logger.warning(f"参考稳态文件不可复用: {e}，使用默认初始化")
            return False

        self._reference_state_path = file_path
        self._reference_state_loaded = True
        logger.info(f"参考稳态已加载: {file_path}")
        return True

    # ------------------------------------------------------------------
    def save_state(self) -> dict:
        """
        导出当前完整运行时状态为 dict（用于运行中暂停/恢复）。

        Returns:
            完整状态字典，可通过 load_state() 恢复。
        """
        return self._get_full_state_dict()

    # ------------------------------------------------------------------
    def load_state(self, state: dict) -> None:
        """
        从 dict 恢复运行时状态。

        Args:
            state: 由 save_state() 导出的状态字典。
        """
        self._set_full_state_dict(state)
        # 状态恢复后重新发布位号
        self._publish_scalar_attributes()


# 注册模型
if __name__ != "__main__":
    InstanceRegistry.register_model("ETHANOL_WATER_DISTILLATION", ETHANOL_WATER_DISTILLATION)
