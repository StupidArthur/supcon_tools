"""
乙醇—水二元汽液平衡热力学后端（阶段 A 定稿）

====================================================================
数据来源（不可替换，参数方向不可互换）
====================================================================

1. Antoine 蒸气压系数与 101.32 kPa 实验乙醇—水 VLE 数据：
   A. Arce, J. Martínez-Ageitos, A. Soto,
   "VLE for water + ethanol + 1-octanol mixtures. Experimental
   measurements and correlations",
   Fluid Phase Equilibria, 122 (1996) 117–129.
   DOI: https://doi.org/10.1016/0378-3812(96)03041-5

2. NRTL 二元交互参数（原始 NRTL，非 association-NRTL）：
   Savannah River National Laboratory 报告
   SRNL-STI-2021-00391, Table 1,
   "Solvent NRTL binary interaction parameters from the Aspen
   Properties databank."
   URL: https://sti.srs.gov/fulltext/SRNL-STI-2021-00391.pdf

3. 纯组分分子量与常压沸点核对：
   NIST Chemistry WebBook
   Ethanol, CAS 64-17-5:
     https://webbook.nist.gov/cgi/cbook.cgi?ID=C64175&Mask=4
   Water, CAS 7732-18-5:
     https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Mask=4

本文实现的全部常数（分子量、Antoine 系数、NRTL 参数）均直接取自上述
公开来源，不是 Agent 自行拟合或回归所得。若实现结果不能复现 spec 预期
误差，应先检查公式、组分顺序、温标和压力单位，不得替换参数源或互换
参数方向。

====================================================================
组分编号与单位（不得改变）
====================================================================

    component 1 = water
    component 2 = ethanol

    温度 T                        K
    压力 P、饱和蒸气压 Psat        kPa(a)（绝对压力）
    分子量                        kg/kmol
    液相、气相组成                 mole fraction，0～1
    NRTL tau、gamma               无量纲
    NRTL 参数 b12、b21             K

热力学核心中禁止混入 ℃、bar、mmHg 或质量分数。Antoine 函数内部按公式
要求把 K 转为 ℃，转换只在该函数内部发生。

====================================================================
Antoine 方程
====================================================================

    log10(P_i_sat / kPa) = A_i - B_i / (T_C + C_i)

    其中 T_C = T_K - 273.15

固定系数：
    water:   A=7.23255, B=1750.286, C=235.000   (输出 kPa, 输入 ℃)
    ethanol: A=7.16879, B=1552.601, C=222.419   (输出 kPa, 输入 ℃)

====================================================================
NRTL 方程与方向
====================================================================

温度相关参数（a + b/T 约定，b 单位为 K，tau 无量纲）：

    tau_12 = tau_water_ethanol   = 3.46 + (-586.0)/T_K
    tau_21 = tau_ethanol_water   = -0.80 + 246.0/T_K
    alpha_12 = alpha_21 = 0.3

方向定义：

    tau_12 对应 water(1)-ethanol(2) 交互
    tau_21 对应 ethanol(2)-water(1) 交互

在 T=298.15 K 时必须得到：
    tau_water_ethanol  = 1.4945463692772092
    tau_ethanol_water = 0.0250880429314104

G 因子：
    G_12 = exp(-alpha * tau_12)
    G_21 = exp(-alpha * tau_21)

令 x1 = x_water = 1 - x_ethanol，x2 = x_ethanol，二元 NRTL 活度系数
闭式：

    ln gamma_1 = x2^2 * [ tau_21 * (G_21/(x1+x2*G_21))^2
                          + tau_12 * G_12 / (x2+x1*G_12)^2 ]

    ln gamma_2 = x1^2 * [ tau_12 * (G_12/(x2+x1*G_12))^2
                          + tau_21 * G_21 / (x1+x2*G_21)^2 ]

返回顺序固定为 (gamma_water, gamma_ethanol)。

====================================================================
泡点与气相组成
====================================================================

低压修正 Raoult 定律（忽略气相逸度系数与 Poynting 修正）：

    y_i * P = x_i * gamma_i * P_i_sat(T)

泡点残差：
    f(T) = x1*gamma1*P1_sat(T) + x2*gamma2*P2_sat(T) - P

求根后：
    y_ethanol = x_ethanol * gamma_ethanol * P_ethanol_sat / P
    y_water   = 1 - y_ethanol

不对 y 做二次归一化，以免掩盖泡点求解残差。

====================================================================
"""

from __future__ import annotations

import math
from typing import Tuple


# ====================================================================
# 纯组分基本常数
# ====================================================================

#: 水的分子量（kg/kmol），来源 NIST Chemistry WebBook, CAS 7732-18-5
MW_WATER_KG_PER_KMOL: float = 18.01528

#: 乙醇的分子量（kg/kmol），来源 NIST Chemistry WebBook, CAS 64-17-5
MW_ETHANOL_KG_PER_KMOL: float = 46.0684


# ====================================================================
# 焓计算参数（阶段 C 能量衡算使用）
# ====================================================================
#
# 焓参考态：T_ref = 273.15 K (0 ℃)，纯液体。
#
# 纯组分液相焓：
#     h_L_i(T) = Cp_L_i * (T - T_ref)
#
# 混合液相焓（理想混合，忽略过剩焓，spec §5.4 允许）：
#     h_L_mix(x, T) = (1-x) * h_L_water(T) + x * h_L_ethanol(T)
#
# 纯组分汽化潜热（在常压沸点附近，330~400 K 范围内取为常数；
# spec §5.4 允许"汽化潜热采用纯组分潜热按组成加权"）：
#     ΔH_vap_water   = 40660 kJ/kmol  (2257 kJ/kg × 18.015 kg/kmol, @ 373.15 K)
#     ΔH_vap_ethanol = 38560 kJ/kmol  (837 kJ/kg × 46.068 kg/kmol, @ 351.5 K)
#
# 纯组分气相焓：
#     h_V_i(T) = h_L_i(T) + ΔH_vap_i
#
# 混合气相焓（理想混合）：
#     h_V_mix(y, T) = (1-y) * h_V_water(T) + y * h_V_ethanol(T)
#
# 低压下液相内能 U ≈ H - P*V_liquid ≈ H（PV 项 < 0.1%），因此塔板液相
# 内能状态 U_i 直接用 M_i * h_L_mix(x_i, T_i) 表示。
#
# 数据来源：
#   - 液相比热：Perry's Chemical Engineers' Handbook, 8th Ed., Table 2-148.
#     水 4.18 kJ/(kg·K) × 18.015 = 75.3 kJ/(kmol·K)
#     乙醇 2.44 kJ/(kg·K) × 46.068 = 112.4 kJ/(kmol·K)
#   - 汽化潜热：NIST WebBook（@ 常压沸点）。
#     水 2257 kJ/kg @ 373.15 K → 40660 kJ/kmol
#     乙醇 837 kJ/kg @ 351.5 K → 38560 kJ/kmol
# 在 330~400 K 范围内 Cp 与 ΔH_vap 的实际变化小于 5%，第一版采用分段常数
# 近似（spec §5.4 允许"温度相关或分段常数"）。

#: 焓参考温度 (K)
T_REF_K: float = 273.15

#: 水的液相摩尔定压热容 (kJ/(kmol·K))
CP_LIQUID_WATER_KJ_PER_KMOL_K: float = 75.3

#: 乙醇的液相摩尔定压热容 (kJ/(kmol·K))
CP_LIQUID_ETHANOL_KJ_PER_KMOL_K: float = 112.4

#: 水的气相摩尔定压热容 (kJ/(kmol·K))，用于气相焓温关系
CP_VAPOR_WATER_KJ_PER_KMOL_K: float = 33.6

#: 乙醇的气相摩尔定压热容 (kJ/(kmol·K))
CP_VAPOR_ETHANOL_KJ_PER_KMOL_K: float = 65.6

#: 水的汽化潜热 (kJ/kmol)，取常压沸点 373.15 K 附近的值
DH_VAP_WATER_KJ_PER_KMOL: float = 40660.0

#: 乙醇的汽化潜热 (kJ/kmol)，取常压沸点 351.5 K 附近的值
DH_VAP_ETHANOL_KJ_PER_KMOL: float = 38560.0

# ====================================================================
# 阶段 2 新增：气相焓/内能公式所需常数（spec §6.2）
# ====================================================================

#: 水的常压沸点 (K)，来源 NIST Chemistry WebBook
T_BOIL_WATER_K: float = 373.15

#: 乙醇的常压沸点 (K)，来源 NIST Chemistry WebBook
T_BOIL_ETHANOL_K: float = 351.50

#: 通用气体常数 (kJ/(kmol·K))，用于气相内能 u = h - R*T
R_KJ_PER_KMOL_K: float = 8.314462618


# ====================================================================
# Antoine 系数（输入 ℃，输出 kPa）
# ====================================================================

#: 水的 Antoine 系数 (A, B, C)，输入温度单位 ℃，输出压力单位 kPa(a)。
#: 来源：Arce et al., Fluid Phase Equilibria 122 (1996) 117–129.
ANTOINE_WATER_KPA_C: Tuple[float, float, float] = (7.23255, 1750.286, 235.000)

#: 乙醇的 Antoine 系数 (A, B, C)，输入温度单位 ℃，输出压力单位 kPa(a)。
#: 来源：Arce et al., Fluid Phase Equilibria 122 (1996) 117–129.
ANTOINE_ETHANOL_KPA_C: Tuple[float, float, float] = (7.16879, 1552.601, 222.419)


# ====================================================================
# NRTL 参数（温度相关，a + b/T 约定）
# ====================================================================

#: tau_12 = tau_water_ethanol 的常数项（无量纲）。
#: 来源：SRNL-STI-2021-00391, Table 1, Aspen Properties databank.
NRTL_WATER_ETHANOL_A: float = 3.46

#: tau_12 = tau_water_ethanol 的温度倒数项系数（单位 K）。
#: 注意：符号为负，表达式为 a + b/T，即 3.46 + (-586.0)/T。
NRTL_WATER_ETHANOL_B_K: float = -586.0

#: tau_21 = tau_ethanol_water 的常数项（无量纲）。
#: 来源：SRNL-STI-2021-00391, Table 1, Aspen Properties databank.
NRTL_ETHANOL_WATER_A: float = -0.80

#: tau_21 = tau_ethanol_water 的温度倒数项系数（单位 K）。
#: 表达式为 -0.80 + 246.0/T。
NRTL_ETHANOL_WATER_B_K: float = 246.0

#: NRTL 非随机性参数 α（无量纲），α_12 = α_21 = 0.3。
NRTL_ALPHA: float = 0.3


# ====================================================================
# 泡点求根器参数
# ====================================================================

#: 第一版支持的压力范围 80～130 kPa(a) 下的全局安全温度搜索区间下限 (K)。
BUBBLE_POINT_T_MIN_K: float = 330.0

#: 全局安全温度搜索区间上限 (K)。
BUBBLE_POINT_T_MAX_K: float = 400.0

#: 泡点求根最大迭代次数。
BUBBLE_POINT_MAX_ITERATIONS: int = 80

#: 泡点求根温度容差 (K)。作为安全网，远紧于压力残差容差，
#: 确保压力残差是主收敛判据，避免纯组分端点 y 精度不足。
BUBBLE_POINT_T_TOLERANCE_K: float = 1e-14

#: 泡点求根压力残差容差 (kPa)。主收敛判据；收敛后 y 精度优于 1e-11。
BUBBLE_POINT_P_TOLERANCE_KPA: float = 1e-9


# ====================================================================
# 纯组分蒸气压
# ====================================================================

def saturation_pressure_kpa(component: str, temperature_k: float) -> float:
    """
    返回指定纯组分在给定温度下的饱和蒸气压（kPa(a)）。

    使用 Antoine 方程：

        log10(P / kPa) = A - B / (T_C + C)

    其中 T_C = T_K - 273.15。Antoine 系数已固定为输入 ℃、输出 kPa。

    Args:
        component: "water" 或 "ethanol"。
        temperature_k: 温度（K）。

    Returns:
        饱和蒸气压（kPa(a)）。

    Raises:
        ValueError: 组分名非法或温度非有限、非正。
    """
    if not math.isfinite(temperature_k) or temperature_k <= 0.0:
        raise ValueError(
            f"temperature_k 必须为正有限数值，实际值={temperature_k!r}"
        )

    if component == "water":
        A, B, C = ANTOINE_WATER_KPA_C
    elif component == "ethanol":
        A, B, C = ANTOINE_ETHANOL_KPA_C
    else:
        raise ValueError(
            f"component 必须为 'water' 或 'ethanol'，实际值={component!r}"
        )

    # Antoine 公式内部把 K 转为 ℃
    t_c = temperature_k - 273.15
    denominator = t_c + C
    if denominator == 0.0:
        raise ValueError(
            f"Antoine 分母为零: t_c={t_c}, C={C}, temperature_k={temperature_k}"
        )
    return 10.0 ** (A - B / denominator)


# ====================================================================
# NRTL 活度系数
# ====================================================================

def _nrtl_tau(temperature_k: float) -> Tuple[float, float]:
    """
    计算 NRTL tau 参数。

    Returns:
        (tau_water_ethanol, tau_ethanol_water)。
    """
    tau_water_ethanol = NRTL_WATER_ETHANOL_A + NRTL_WATER_ETHANOL_B_K / temperature_k
    tau_ethanol_water = NRTL_ETHANOL_WATER_A + NRTL_ETHANOL_WATER_B_K / temperature_k
    return tau_water_ethanol, tau_ethanol_water


def nrtl_activity_coefficients(
    x_ethanol: float,
    temperature_k: float,
) -> Tuple[float, float]:
    """
    计算乙醇—水二元 NRTL 活度系数。

    采用 spec §5 中的二元闭式，避免从通用多组分公式临时推导下标。

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。
        temperature_k: 温度（K）。

    Returns:
        (gamma_water, gamma_ethanol)。

    Raises:
        ValueError: 组成越界或温度非有限、非正。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    if not math.isfinite(temperature_k) or temperature_k <= 0.0:
        raise ValueError(
            f"temperature_k 必须为正有限数值，实际值={temperature_k!r}"
        )

    x2 = x_ethanol          # 乙醇
    x1 = 1.0 - x2           # 水

    tau_12, tau_21 = _nrtl_tau(temperature_k)
    # tau_12 = tau_water_ethanol, tau_21 = tau_ethanol_water

    G_12 = math.exp(-NRTL_ALPHA * tau_12)
    G_21 = math.exp(-NRTL_ALPHA * tau_21)

    # 分母项（不允许为零；在物理合理组成与温度下为正）
    denom1 = x1 + x2 * G_21
    denom2 = x2 + x1 * G_12
    if denom1 == 0.0 or denom2 == 0.0:
        raise ValueError(
            f"NRTL 分母为零: x_ethanol={x_ethanol}, T={temperature_k} K, "
            f"denom1={denom1}, denom2={denom2}"
        )

    # ln gamma_1 (water)
    term1_water = tau_21 * (G_21 / denom1) ** 2
    term2_water = tau_12 * G_12 / (denom2 ** 2)
    ln_gamma_water = (x2 ** 2) * (term1_water + term2_water)

    # ln gamma_2 (ethanol)
    term1_ethanol = tau_12 * (G_12 / denom2) ** 2
    term2_ethanol = tau_21 * G_21 / (denom1 ** 2)
    ln_gamma_ethanol = (x1 ** 2) * (term1_ethanol + term2_ethanol)

    gamma_water = math.exp(ln_gamma_water)
    gamma_ethanol = math.exp(ln_gamma_ethanol)
    return gamma_water, gamma_ethanol


# ====================================================================
# 泡点温度与气相组成
# ====================================================================

def _bubble_pressure_residual(
    x_ethanol: float,
    temperature_k: float,
    pressure_kpa: float,
) -> float:
    """
    泡点残差 f(T) = Σ x_i γ_i P_i_sat(T) - P。

    内部使用，不做输入校验（由调用方负责）。
    """
    x2 = x_ethanol
    x1 = 1.0 - x2

    gamma_water, gamma_ethanol = nrtl_activity_coefficients(x_ethanol, temperature_k)
    p_water_sat = saturation_pressure_kpa("water", temperature_k)
    p_ethanol_sat = saturation_pressure_kpa("ethanol", temperature_k)

    return x1 * gamma_water * p_water_sat + x2 * gamma_ethanol * p_ethanol_sat - pressure_kpa


def bubble_point_temperature(
    x_ethanol: float,
    pressure_kpa: float,
    previous_temperature_k: float | None = None,
) -> Tuple[float, float]:
    """
    计算乙醇—水混合物在指定压力下的泡点温度与平衡气相乙醇摩尔分数。

    使用有界二分法求解 f(T) = Σ x_i γ_i P_i_sat(T) - P = 0。
    不引入 SciPy 依赖。

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。
        pressure_kpa: 压力（kPa(a)，正有限）。
        previous_temperature_k: 上一周期温度初值（K），仅用于缩小有效括区，
            不能改变最终解。若为 None 或缩小后括区无效，则使用全局安全区间。

    Returns:
        (bubble_temperature_k, y_ethanol)。

    Raises:
        ValueError: 输入非法，或求根区间两端残差不异号（无法保证唯一根）。
        RuntimeError: 达到最大迭代次数仍未收敛。
    """
    # ---- 输入校验 ----
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    if not math.isfinite(pressure_kpa) or pressure_kpa <= 0.0:
        raise ValueError(
            f"pressure_kpa 必须为正有限数值，实际值={pressure_kpa!r}"
        )

    # ---- 选择求根括区 ----
    # 默认全局安全区间
    t_low = BUBBLE_POINT_T_MIN_K
    t_high = BUBBLE_POINT_T_MAX_K

    # 若提供 previous_temperature_k，尝试缩小括区以加速
    # 但最终解必须与使用全局区间一致（f 单调，唯一根）
    if previous_temperature_k is not None:
        if (
            math.isfinite(previous_temperature_k)
            and BUBBLE_POINT_T_MIN_K < previous_temperature_k < BUBBLE_POINT_T_MAX_K
        ):
            # 尝试以 previous 为中心 ±15K 的窄区间
            half_width = 15.0
            cand_low = max(BUBBLE_POINT_T_MIN_K, previous_temperature_k - half_width)
            cand_high = min(BUBBLE_POINT_T_MAX_K, previous_temperature_k + half_width)
            if cand_high - cand_low > 1.0:
                f_cand_low = _bubble_pressure_residual(x_ethanol, cand_low, pressure_kpa)
                f_cand_high = _bubble_pressure_residual(x_ethanol, cand_high, pressure_kpa)
                # 只有当窄区间两端异号时才采用，否则回退到全局区间
                if f_cand_low * f_cand_high < 0.0:
                    t_low = cand_low
                    t_high = cand_high

    # ---- 验证括区两端残差异号 ----
    f_low = _bubble_pressure_residual(x_ethanol, t_low, pressure_kpa)
    f_high = _bubble_pressure_residual(x_ethanol, t_high, pressure_kpa)

    if f_low * f_high > 0.0:
        raise ValueError(
            f"泡点求根区间两端残差不异号，无法保证唯一根: "
            f"x_ethanol={x_ethanol}, pressure_kpa={pressure_kpa}, "
            f"T_low={t_low} K (f={f_low}), T_high={t_high} K (f={f_high})"
        )

    # 端点恰好为零的边界情况
    if f_low == 0.0:
        t_bubble = t_low
    elif f_high == 0.0:
        t_bubble = t_high
    else:
        # ---- 有界二分 ----
        t_bubble = 0.0
        for _ in range(BUBBLE_POINT_MAX_ITERATIONS):
            t_mid = 0.5 * (t_low + t_high)
            f_mid = _bubble_pressure_residual(x_ethanol, t_mid, pressure_kpa)

            if abs(f_mid) < BUBBLE_POINT_P_TOLERANCE_KPA:
                t_bubble = t_mid
                break
            if (t_high - t_low) * 0.5 < BUBBLE_POINT_T_TOLERANCE_K:
                t_bubble = t_mid
                break

            if f_low * f_mid < 0.0:
                t_high = t_mid
                f_high = f_mid
            else:
                t_low = t_mid
                f_low = f_mid
        else:
            # 达到最大迭代次数仍未达到容差
            t_bubble = 0.5 * (t_low + t_high)
            # 验证最终残差是否足够小
            final_residual = abs(_bubble_pressure_residual(x_ethanol, t_bubble, pressure_kpa))
            if final_residual > 1e-6:
                raise RuntimeError(
                    f"泡点求根未收敛: x_ethanol={x_ethanol}, "
                    f"pressure_kpa={pressure_kpa}, T={t_bubble} K, "
                    f"残差={final_residual} kPa"
                )

    # ---- 计算气相组成 ----
    # y_ethanol = x_ethanol * gamma_ethanol * P_ethanol_sat / P
    # y_water = 1 - y_ethanol（不单独归一化）
    gamma_water, gamma_ethanol = nrtl_activity_coefficients(x_ethanol, t_bubble)
    p_ethanol_sat = saturation_pressure_kpa("ethanol", t_bubble)
    y_ethanol = x_ethanol * gamma_ethanol * p_ethanol_sat / pressure_kpa

    return t_bubble, y_ethanol


def vapor_composition_at_state(
    x_ethanol: float,
    temperature_k: float,
    pressure_kpa: float,
    normalize: bool = True,
) -> Tuple[float, float, float]:
    """
    在给定 (T, x, P) 状态下计算气相乙醇摩尔分数与泡点残差。

    用于阶段 C：塔板温度由能量衡算决定，可能偏离泡点。此时气相组成仍按
    低压修正 Raoult 定律计算，并按需归一化以维持 sum(y)=1。

        y_ethanol_raw = x_ethanol * gamma_ethanol * P_ethanol_sat(T) / P
        y_water_raw   = (1-x_ethanol) * gamma_water * P_water_sat(T) / P
        sum_y         = y_ethanol_raw + y_water_raw

    若 normalize=True 且 sum_y > 0，则返回归一化后的 y_ethanol；否则返回
    原始 y_ethanol_raw。同时返回泡点残差 sum_y - 1，可用于诊断系统是否
    处于泡点（残差≈0）、过热（残差>0）或过冷（残差<0）状态。

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。
        temperature_k: 温度 (K)。
        pressure_kpa: 压力 (kPa(a)，正有限)。
        normalize: 是否归一化使 sum(y)=1，默认 True。

    Returns:
        (y_ethanol, y_water_raw_sum, bubble_residual)
        - y_ethanol: 归一化（或原始）气相乙醇摩尔分数
        - y_water_raw_sum: 原始 sum(y_water + y_ethanol)（=泡点残差+1）
        - bubble_residual: sum_y - 1，正表示过热，负表示过冷

    Raises:
        ValueError: 输入非法。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    if not math.isfinite(temperature_k) or temperature_k <= 0.0:
        raise ValueError(
            f"temperature_k 必须为正有限数值，实际值={temperature_k!r}"
        )
    if not math.isfinite(pressure_kpa) or pressure_kpa <= 0.0:
        raise ValueError(
            f"pressure_kpa 必须为正有限数值，实际值={pressure_kpa!r}"
        )

    x2 = x_ethanol
    x1 = 1.0 - x2

    gamma_water, gamma_ethanol = nrtl_activity_coefficients(x_ethanol, temperature_k)
    p_water_sat = saturation_pressure_kpa("water", temperature_k)
    p_ethanol_sat = saturation_pressure_kpa("ethanol", temperature_k)

    y_ethanol_raw = x2 * gamma_ethanol * p_ethanol_sat / pressure_kpa
    y_water_raw = x1 * gamma_water * p_water_sat / pressure_kpa
    sum_y = y_ethanol_raw + y_water_raw

    if normalize and sum_y > 1e-15:
        y_ethanol = y_ethanol_raw / sum_y
    else:
        y_ethanol = y_ethanol_raw

    return y_ethanol, sum_y, sum_y - 1.0


# ====================================================================
# 质量分数 ↔ 摩尔分数转换
# ====================================================================

def ethanol_mass_fraction_to_mole_fraction(w_ethanol: float) -> float:
    """
    乙醇质量分数 → 摩尔分数。

        x_E = (w_E / MW_E) / (w_E / MW_E + (1 - w_E) / MW_W)

    Args:
        w_ethanol: 乙醇质量分数（0～1）。

    Returns:
        乙醇摩尔分数。

    Raises:
        ValueError: 输入越界或非有限。
    """
    if not math.isfinite(w_ethanol) or not (0.0 <= w_ethanol <= 1.0):
        raise ValueError(
            f"w_ethanol 必须位于 [0, 1]，实际值={w_ethanol!r}"
        )
    w_e = w_ethanol
    w_w = 1.0 - w_e
    return (w_e / MW_ETHANOL_KG_PER_KMOL) / (
        w_e / MW_ETHANOL_KG_PER_KMOL + w_w / MW_WATER_KG_PER_KMOL
    )


def ethanol_mole_fraction_to_mass_fraction(x_ethanol: float) -> float:
    """
    乙醇摩尔分数 → 质量分数。

        w_E = x_E * MW_E / (x_E * MW_E + (1 - x_E) * MW_W)

    Args:
        x_ethanol: 乙醇摩尔分数（0～1）。

    Returns:
        乙醇质量分数。

    Raises:
        ValueError: 输入越界或非有限。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    x_e = x_ethanol
    x_w = 1.0 - x_e
    return (x_e * MW_ETHANOL_KG_PER_KMOL) / (
        x_e * MW_ETHANOL_KG_PER_KMOL + x_w * MW_WATER_KG_PER_KMOL
    )


# ====================================================================
# 焓与汽化潜热（阶段 C 能量衡算使用）
# ====================================================================

def liquid_enthalpy_kj_per_kmol(x_ethanol: float, temperature_k: float) -> float:
    """
    二元乙醇—水液相混合物摩尔焓 (kJ/kmol)。

    理想混合，忽略过剩焓（spec §5.4 允许）。

        h_L_mix(x, T) = (1-x) * Cp_L_water * (T - T_ref)
                       + x * Cp_L_ethanol * (T - T_ref)

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。
        temperature_k: 温度 (K)。

    Returns:
        摩尔液相焓 (kJ/kmol)。

    Raises:
        ValueError: 输入越界或非有限。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    if not math.isfinite(temperature_k):
        raise ValueError(f"temperature_k 必须有限，实际值={temperature_k!r}")

    x_e = x_ethanol
    x_w = 1.0 - x_e
    delta_t = temperature_k - T_REF_K
    return x_w * CP_LIQUID_WATER_KJ_PER_KMOL_K * delta_t + x_e * CP_LIQUID_ETHANOL_KJ_PER_KMOL_K * delta_t


def vapor_enthalpy_kj_per_kmol(y_ethanol: float, temperature_k: float) -> float:
    """
    二元乙醇—水气相混合物摩尔焓 (kJ/kmol)。

    阶段 2 公式（spec §6.2）：
        h_v_i(T) = Cp_L_i * (T_b_i - T_ref) + ΔH_vap_i + Cp_V_i * (T - T_b_i)
        h_vapor(y, T) = (1-y) * h_v_water(T) + y * h_v_ethanol(T)

    物理含义：以 T_ref 下纯液相为参考态，先把液体从 T_ref 显热到沸点 T_b，
    在 T_b 下汽化（ΔH_vap），再把气相从 T_b 显热到 T。这样气相热容与液相
    热容分别使用各自的常数，更符合真实物性。

    Args:
        y_ethanol: 气相乙醇摩尔分数（0～1）。
        temperature_k: 温度 (K)。

    Returns:
        摩尔气相焓 (kJ/kmol)。
    """
    if not math.isfinite(y_ethanol) or not (0.0 <= y_ethanol <= 1.0):
        raise ValueError(
            f"y_ethanol 必须位于 [0, 1]，实际值={y_ethanol!r}"
        )
    if not math.isfinite(temperature_k):
        raise ValueError(f"temperature_k 必须有限，实际值={temperature_k!r}")

    y_e = y_ethanol
    y_w = 1.0 - y_e
    # 纯组分气相焓：液相显热到沸点 + 沸点汽化潜热 + 气相显热到 T
    h_v_water = (
        CP_LIQUID_WATER_KJ_PER_KMOL_K * (T_BOIL_WATER_K - T_REF_K)
        + DH_VAP_WATER_KJ_PER_KMOL
        + CP_VAPOR_WATER_KJ_PER_KMOL_K * (temperature_k - T_BOIL_WATER_K)
    )
    h_v_ethanol = (
        CP_LIQUID_ETHANOL_KJ_PER_KMOL_K * (T_BOIL_ETHANOL_K - T_REF_K)
        + DH_VAP_ETHANOL_KJ_PER_KMOL
        + CP_VAPOR_ETHANOL_KJ_PER_KMOL_K * (temperature_k - T_BOIL_ETHANOL_K)
    )
    return y_w * h_v_water + y_e * h_v_ethanol


def vapor_internal_energy_kj_per_kmol(y_ethanol: float, temperature_k: float) -> float:
    """
    二元乙醇—水气相混合物摩尔内能 (kJ/kmol)。

    低压理想气体近似：
        u_vapor(y, T) = h_vapor(y, T) - R * T

    其中 R = 8.314462618 kJ/(kmol·K)。

    Args:
        y_ethanol: 气相乙醇摩尔分数（0～1）。
        temperature_k: 温度 (K)。

    Returns:
        摩尔气相内能 (kJ/kmol)。
    """
    h_vapor = vapor_enthalpy_kj_per_kmol(y_ethanol, temperature_k)
    return h_vapor - R_KJ_PER_KMOL_K * temperature_k


def temperature_from_vapor_internal_energy(
    internal_energy_kj_per_kmol: float,
    y_ethanol: float,
) -> float:
    """
    由气相单位物质量内能反算温度 (K)（解析解，常数热容）。

    推导（spec §6.2）：
        h_v_i(T) = Cp_L_i*(T_b_i - T_ref) + ΔH_vap_i + Cp_V_i*(T - T_b_i)
                 = A_i + Cp_V_i * T
        其中 A_i = Cp_L_i*(T_b_i - T_ref) + ΔH_vap_i - Cp_V_i*T_b_i

        h_vapor(y, T) = (1-y)*h_v_water(T) + y*h_v_ethanol(T)
                      = A + B_h * T
        其中:
            A   = (1-y)*A_w + y*A_e
            B_h = (1-y)*Cp_V_water + y*Cp_V_ethanol

        u_vapor(y, T) = h_vapor(y, T) - R*T = A + (B_h - R)*T = A + B*T
        其中 B = B_h - R

        解析反算: T = (u - A) / B

    Args:
        internal_energy_kj_per_kmol: 气相单位物质量内能 (kJ/kmol)。
            调用方应先计算 U_vapor_kJ / N_vapor_kgmol 得到此值。
        y_ethanol: 气相乙醇摩尔分数（0～1）。

    Returns:
        温度 (K)。

    Raises:
        ValueError: 组成越界或非有限。
    """
    if not math.isfinite(y_ethanol) or not (0.0 <= y_ethanol <= 1.0):
        raise ValueError(
            f"y_ethanol 必须位于 [0, 1]，实际值={y_ethanol!r}"
        )
    if not math.isfinite(internal_energy_kj_per_kmol):
        raise ValueError(
            f"internal_energy_kj_per_kmol 必须有限，实际值={internal_energy_kj_per_kmol!r}"
        )

    y_e = y_ethanol
    y_w = 1.0 - y_e

    # A_i = Cp_L_i*(T_b_i - T_ref) + ΔH_vap_i - Cp_V_i*T_b_i
    A_w = (
        CP_LIQUID_WATER_KJ_PER_KMOL_K * (T_BOIL_WATER_K - T_REF_K)
        + DH_VAP_WATER_KJ_PER_KMOL
        - CP_VAPOR_WATER_KJ_PER_KMOL_K * T_BOIL_WATER_K
    )
    A_e = (
        CP_LIQUID_ETHANOL_KJ_PER_KMOL_K * (T_BOIL_ETHANOL_K - T_REF_K)
        + DH_VAP_ETHANOL_KJ_PER_KMOL
        - CP_VAPOR_ETHANOL_KJ_PER_KMOL_K * T_BOIL_ETHANOL_K
    )

    A = y_w * A_w + y_e * A_e
    B_h = y_w * CP_VAPOR_WATER_KJ_PER_KMOL_K + y_e * CP_VAPOR_ETHANOL_KJ_PER_KMOL_K
    B = B_h - R_KJ_PER_KMOL_K

    # B 应严格为正（Cp_V_water=33.6, Cp_V_ethanol=65.6, R=8.314）
    if B <= 0.0:
        raise ValueError(
            f"气相热容系数 B 非正: B={B}, y_ethanol={y_ethanol}"
        )

    return (internal_energy_kj_per_kmol - A) / B


def heat_of_vaporization_kj_per_kmol(x_ethanol: float) -> float:
    """
    二元乙醇—水混合物按组成加权的摩尔汽化潜热 (kJ/kmol)。

        ΔH_vap_mix(x) = (1-x) * ΔH_vap_water + x * ΔH_vap_ethanol

    spec §5.4 允许"汽化潜热采用纯组分潜热按组成加权"。第一版忽略温度
    对 ΔH_vap 的影响（在 330~400 K 范围内变化 <5%）。

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。

    Returns:
        混合物摩尔汽化潜热 (kJ/kmol)。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    x_e = x_ethanol
    x_w = 1.0 - x_e
    return x_w * DH_VAP_WATER_KJ_PER_KMOL + x_e * DH_VAP_ETHANOL_KJ_PER_KMOL


def liquid_heat_capacity_kj_per_kmol_k(x_ethanol: float) -> float:
    """
    二元乙醇—水液相混合物摩尔定压热容 (kJ/(kmol·K))。

        Cp_L_mix(x) = (1-x) * Cp_L_water + x * Cp_L_ethanol

    用于由内能状态反算温度。

    Args:
        x_ethanol: 液相乙醇摩尔分数（0～1）。

    Returns:
        混合物液相摩尔热容 (kJ/(kmol·K))。
    """
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    x_e = x_ethanol
    x_w = 1.0 - x_e
    return x_w * CP_LIQUID_WATER_KJ_PER_KMOL_K + x_e * CP_LIQUID_ETHANOL_KJ_PER_KMOL_K


def temperature_from_internal_energy(
    internal_energy_kj: float,
    total_moles_kgmol: float,
    x_ethanol: float,
) -> float:
    """
    由液相内能状态反算温度 (K)。

    低压下 U ≈ H = M * h_L_mix(x, T)，因此：

        T = T_ref + U / (M * Cp_L_mix(x))

    Args:
        internal_energy_kj: 液相总内能 (kJ)。
        total_moles_kgmol: 液相总物质量 (kmol)。
        x_ethanol: 液相乙醇摩尔分数（0～1）。

    Returns:
        温度 (K)。

    Raises:
        ValueError: 物质量非正或组成越界。
    """
    if not math.isfinite(total_moles_kgmol) or total_moles_kgmol <= 0.0:
        raise ValueError(
            f"total_moles_kgmol 必须为正有限数值，实际值={total_moles_kgmol!r}"
        )
    if not math.isfinite(x_ethanol) or not (0.0 <= x_ethanol <= 1.0):
        raise ValueError(
            f"x_ethanol 必须位于 [0, 1]，实际值={x_ethanol!r}"
        )
    cp_mix = liquid_heat_capacity_kj_per_kmol_k(x_ethanol)
    if cp_mix <= 0.0:
        raise ValueError(f"Cp_L_mix 非正: {cp_mix}")
    return T_REF_K + internal_energy_kj / (total_moles_kgmol * cp_mix)
