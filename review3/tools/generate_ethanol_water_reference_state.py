"""
乙醇—水精馏塔参考稳态生成器（todo/5.md §9.3 + 修复指令 §4）。

核心策略（修复指令 §4）：
    WARM_GUESS
    → 使用动态模型原有 RHS 建立稳态非线性残差
    → scipy.optimize.least_squares 求一致稳态
    → 安装求解结果
    → 用"直接实际流量入口"做短验证
    → 把相同实际流量反算为阀位
    → 做直接流量/阀位单步等价性验证
    → 用标称阀位做连续动态稳态窗口和漂移验证
    → 全部门禁通过后原子写入正式 JSON

代数求解器不另写一套精馏模型，只调用动态模型现有的：
    _compute_algebraic()
    _calculate_hydraulics()
    _calculate_rhs()
因此代数求解和动态运行共享同一套 VLE、物料、能量、再沸和冷凝机理。

使用方法：
    python tools/generate_ethanol_water_reference_state.py

输出：
    components/programs/data/ethanol_water_reference_state.json
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
from scipy.optimize import least_squares

import components.programs  # noqa: F401 触发组件注册
from components.programs.ethanol_water_distillation import (
    ETHANOL_WATER_DISTILLATION,
    R_UNIVERSAL_KPA_M3_PER_KMOL_K,
)
from components.thermo.ethanol_water import (
    MW_ETHANOL_KG_PER_KMOL,
    MW_WATER_KG_PER_KMOL,
    T_REF_K,
    bubble_point_temperature,
    ethanol_mass_fraction_to_mole_fraction,
    ethanol_mole_fraction_to_mass_fraction,
    heat_of_vaporization_kj_per_kmol,
    liquid_enthalpy_kj_per_kmol,
    liquid_heat_capacity_kj_per_kmol_k,
    vapor_enthalpy_kj_per_kmol,
    vapor_internal_energy_kj_per_kmol,
    temperature_from_vapor_internal_energy,
)


# ====================================================================
# 专用异常
# ====================================================================
class ReferenceStateGenerationError(RuntimeError):
    """参考稳态生成门禁失败时抛出。"""


# ====================================================================
# 参考工况参数（todo/5.md §2.3 + §3.2）
# ====================================================================
REFERENCE_PARAMS: Dict[str, Any] = {
    "cycle_time": 0.5,
    "max_internal_step": 0.25,
    "initialization_mode": "WARM_GUESS",
    "random_seed": 20260719,
    # 标称流量初值（kmol/s）—— 物料衡算闭合：F = D + B（todo/5.md §3.1）
    "feed_flow_kgmol_per_s": 0.00130716777,
    "distillate_flow_kgmol_per_s": 0.00020933521,
    "bottoms_flow_kgmol_per_s": 0.00109783256,
    "reflux_flow_kgmol_per_s": 0.00062800562,  # R = 3.0
    "vapor_boilup_kgmol_per_s": 0.00083734082,  # (R+1)*D
    # 进料
    "feed_ethanol_wt": 0.25,
    "feed_temperature_c": 60.0,
}

# 目标稳态操作点（todo/5.md §2.3 + §9.4）
TARGET_TOP_ETHANOL_WT = 0.85
TARGET_BOTTOM_ETHANOL_WT = 0.015
TARGET_TOP_PRESSURE_KPA = 101.325
TARGET_DRUM_LEVEL_PCT = 50.0
TARGET_SUMP_LEVEL_PCT = 50.0

# 固定进料（不进入未知向量）
FIXED_FEED_FLOW_KGMOL_PER_S = 0.00130716777
FIXED_FEED_ETHANOL_WT = 0.25
FIXED_FEED_TEMPERATURE_C = 60.0

# 蒸汽/冷却水初猜（todo/5.md §3.2）
INITIAL_STEAM_FLOW_KG_H = 60.47
INITIAL_COOLING_FLOW_KG_H = 3500.0

# 蒸汽 V_boil 初猜（仅供 least_squares x0，不再作为运行时强制输入）
INITIAL_VAPOR_BOILUP_GUESS_KGMOL_PER_S = 0.00083734082

# 51 个未知量的分段索引（修复指令 §8.2）
# 塔板状态：36 个 (M_tray[12], xE_tray[12], T_tray[12])
# 回流罐：3 个 (M_drum, xE_drum, T_drum)
# 塔釜：3 个 (M_sump, xE_sump, T_sump)
# 气相库存：3 个 (P_top, yE_vapor, T_vapor)
# 稳态操作变量：5 个 (R, D, B, steam, cooling)
# CMO 气相流量固定点变量：1 个 (V_boil_trial)
N_TRAYS = 12
N_UNKNOWN = 51


# ====================================================================
# 操作量 dataclass（修复指令 §9）
# ====================================================================
@dataclass(frozen=True)
class OperatingInputs:
    """不可变的实际操作量。直接模式、阀位反算和元数据共享此对象。"""
    feed_flow_kgmol_per_s: float
    reflux_flow_kgmol_per_s: float
    distillate_flow_kgmol_per_s: float
    bottoms_flow_kgmol_per_s: float
    steam_flow_kg_h: float
    cooling_flow_kg_h: float


# ====================================================================
# 状态快照（修复指令 §10.1）
# ====================================================================
@dataclass
class StateSnapshot:
    M_tray: np.ndarray
    nE_tray: np.ndarray
    U_tray: np.ndarray
    M_drum: float
    nE_drum: float
    U_drum: float
    M_sump: float
    nE_sump: float
    U_sump: float
    N_vapor: float
    nE_vapor: float
    U_vapor: float
    T_tray: np.ndarray
    T_drum: float
    T_sump: float
    T_vapor: float
    P_top: float


def capture_state_snapshot(col: ETHANOL_WATER_DISTILLATION) -> StateSnapshot:
    """捕获当前模型状态为快照（数组必须 .copy()）。"""
    return StateSnapshot(
        M_tray=np.array(col._M_tray, dtype=np.float64).copy(),
        nE_tray=np.array(col._nE_tray, dtype=np.float64).copy(),
        U_tray=np.array(col._U_tray, dtype=np.float64).copy(),
        M_drum=float(col._M_drum),
        nE_drum=float(col._nE_drum),
        U_drum=float(col._U_drum),
        M_sump=float(col._M_sump),
        nE_sump=float(col._nE_sump),
        U_sump=float(col._U_sump),
        N_vapor=float(col._N_vapor),
        nE_vapor=float(col._nE_vapor),
        U_vapor=float(col._U_vapor),
        T_tray=np.array(col._T_tray, dtype=np.float64).copy(),
        T_drum=float(col._T_drum),
        T_sump=float(col._T_sump),
        T_vapor=float(col._T_vapor),
        P_top=float(col._p_top_kpa),
    )


# ====================================================================
# 51 变量打包/解包
# ====================================================================
def pack_unknowns(
    col: ETHANOL_WATER_DISTILLATION,
    op: OperatingInputs,
    V_trial: float,
) -> np.ndarray:
    """从模型状态和操作量打包成 51 维未知向量。"""
    z = np.zeros(N_UNKNOWN, dtype=np.float64)
    idx = 0
    # 塔板 M/xE/T (36)
    for i in range(N_TRAYS):
        z[idx] = float(col._M_tray[i])
        idx += 1
    for i in range(N_TRAYS):
        xE = float(col._nE_tray[i] / col._M_tray[i]) if col._M_tray[i] > 1e-15 else 0.0
        z[idx] = max(0.0, min(1.0, xE))
        idx += 1
    for i in range(N_TRAYS):
        z[idx] = float(col._T_tray[i])
        idx += 1
    # 回流罐 M/xE/T (3)
    z[idx] = float(col._M_drum); idx += 1
    xE_drum = float(col._nE_drum / col._M_drum) if col._M_drum > 1e-15 else 0.0
    z[idx] = max(0.0, min(1.0, xE_drum)); idx += 1
    z[idx] = float(col._T_drum); idx += 1
    # 塔釜 M/xE/T (3)
    z[idx] = float(col._M_sump); idx += 1
    xE_sump = float(col._nE_sump / col._M_sump) if col._M_sump > 1e-15 else 0.0
    z[idx] = max(0.0, min(1.0, xE_sump)); idx += 1
    z[idx] = float(col._T_sump); idx += 1
    # 气相库存 P/yE/T (3)
    z[idx] = float(col._p_top_kpa); idx += 1
    z[idx] = float(col._yE_vapor); idx += 1
    z[idx] = float(col._T_vapor); idx += 1
    # 操作变量 R/D/B/steam/cooling (5)
    z[idx] = op.reflux_flow_kgmol_per_s; idx += 1
    z[idx] = op.distillate_flow_kgmol_per_s; idx += 1
    z[idx] = op.bottoms_flow_kgmol_per_s; idx += 1
    z[idx] = op.steam_flow_kg_h; idx += 1
    z[idx] = op.cooling_flow_kg_h; idx += 1
    # V_boil_trial (1)
    z[idx] = float(V_trial); idx += 1
    assert idx == N_UNKNOWN, f"打包索引错误: {idx} != {N_UNKNOWN}"
    return z


def unpack_unknowns(z: np.ndarray) -> Dict[str, Any]:
    """解包 51 维未知向量为状态字典。"""
    idx = 0
    M_tray = np.array(z[idx:idx + N_TRAYS], dtype=np.float64); idx += N_TRAYS
    xE_tray = np.array(z[idx:idx + N_TRAYS], dtype=np.float64); idx += N_TRAYS
    T_tray = np.array(z[idx:idx + N_TRAYS], dtype=np.float64); idx += N_TRAYS
    M_drum = float(z[idx]); idx += 1
    xE_drum = float(z[idx]); idx += 1
    T_drum = float(z[idx]); idx += 1
    M_sump = float(z[idx]); idx += 1
    xE_sump = float(z[idx]); idx += 1
    T_sump = float(z[idx]); idx += 1
    P_top = float(z[idx]); idx += 1
    yE_vapor = float(z[idx]); idx += 1
    T_vapor = float(z[idx]); idx += 1
    R_flow = float(z[idx]); idx += 1
    D_flow = float(z[idx]); idx += 1
    B_flow = float(z[idx]); idx += 1
    steam_kg_h = float(z[idx]); idx += 1
    cooling_kg_h = float(z[idx]); idx += 1
    V_trial = float(z[idx]); idx += 1
    assert idx == N_UNKNOWN, f"解包索引错误: {idx} != {N_UNKNOWN}"

    # 转换为动态模型内部状态表示：M/nE/U + 气相 N/nE/U
    nE_tray = M_tray * xE_tray
    U_tray = M_tray * np.array([
        liquid_enthalpy_kj_per_kmol(float(xE_tray[i]), float(T_tray[i]))
        for i in range(N_TRAYS)
    ], dtype=np.float64)
    nE_drum = M_drum * xE_drum
    U_drum = M_drum * liquid_enthalpy_kj_per_kmol(xE_drum, T_drum)
    nE_sump = M_sump * xE_sump
    U_sump = M_sump * liquid_enthalpy_kj_per_kmol(xE_sump, T_sump)

    # 气相状态（修复指令 §8.3）
    # N_vapor = P_top * V_gas / (R * T_vapor)
    # nE_vapor = N_vapor * yE_vapor
    # U_vapor = N_vapor * u_vapor(yE_vapor, T_vapor)
    # 注：vapor_volume_m3 在 col 中持有，这里先返回 P/yE/T，残差评估函数内部再做反算
    return {
        "M_tray": M_tray, "nE_tray": nE_tray, "U_tray": U_tray,
        "M_drum": M_drum, "nE_drum": nE_drum, "U_drum": U_drum,
        "M_sump": M_sump, "nE_sump": nE_sump, "U_sump": U_sump,
        "P_top": P_top, "yE_vapor": yE_vapor, "T_vapor": T_vapor,
        "T_tray": T_tray, "T_drum": T_drum, "T_sump": T_sump,
        "xE_tray": xE_tray, "xE_drum": xE_drum, "xE_sump": xE_sump,
        "R_flow": R_flow, "D_flow": D_flow, "B_flow": B_flow,
        "steam_kg_h": steam_kg_h, "cooling_kg_h": cooling_kg_h,
        "V_trial": V_trial,
    }


# ====================================================================
# 稳态残差评估（修复指令 §8.5）
# ====================================================================
def evaluate_steady_residual(
    z: np.ndarray,
    col: ETHANOL_WATER_DISTILLATION,
) -> np.ndarray:
    """
    51 维稳态残差评估函数（修复指令 §8.4-§8.6）。

    调用顺序严格按 §8.5：
    1. 解包 z
    2. 构造 M/nE/U 和气相状态
    3. 保存 V_trial
    4. 调用 _compute_algebraic(..., V_trial)
    5. 调用 _calculate_hydraulics(M_tray)
    6. 调用 _calculate_rhs(..., direct_vapor_bypass=None)
    7. 从 col._V_boil_internal 读取 V_calculated
    8. 拼接并缩放 51 个残差
    9. 返回一维 np.float64 数组

    重要约束：direct_vapor_bypass 必须始终为 None
    """
    try:
        u = unpack_unknowns(z)

        # 构造气相 N/nE/U（修复指令 §8.3）
        P_top = max(u["P_top"], 1e-6)
        T_vapor = max(u["T_vapor"], 250.0)
        yE_vapor = max(0.0, min(0.999999, u["yE_vapor"]))
        N_vapor = P_top * col._vapor_volume_m3 / (R_UNIVERSAL_KPA_M3_PER_KMOL_K * T_vapor)
        nE_vapor = N_vapor * yE_vapor
        U_vapor = N_vapor * vapor_internal_energy_kj_per_kmol(yE_vapor, T_vapor)

        V_trial = max(u["V_trial"], 1e-12)

        # 进料参数
        feed_xE = ethanol_mass_fraction_to_mole_fraction(FIXED_FEED_ETHANOL_WT)
        feed_temperature_k = FIXED_FEED_TEMPERATURE_C + 273.15

        # 1) 代数量（VLE、温度、压力、气相组成）
        algebraic = col._compute_algebraic(
            u["M_tray"], u["nE_tray"], u["U_tray"],
            u["M_drum"], u["nE_drum"], u["U_drum"],
            u["M_sump"], u["nE_sump"], u["U_sump"],
            N_vapor, nE_vapor, U_vapor,
            V_trial,
        )
        (
            T_tray_calc, yE_tray, T_drum_calc, T_sump_calc, yE_sump,
            p_top_calc, pressure_kpa, p_sump,
            T_vapor_avg, yE_vapor_calc, T_vapor_calc,
        ) = algebraic

        # 2) 水力学（向下液相流量）
        L = col._calculate_hydraulics(u["M_tray"])

        # 3) RHS（状态导数）；direct_vapor_bypass 必须为 None（修复指令 §8.5）
        rhs = col._calculate_rhs(
            u["M_tray"], u["nE_tray"], u["U_tray"],
            u["M_drum"], u["nE_drum"], u["U_drum"],
            u["M_sump"], u["nE_sump"], u["U_sump"],
            N_vapor, nE_vapor, U_vapor,
            L, V_trial,
            T_tray_calc, yE_tray,
            T_drum_calc, T_sump_calc, yE_sump,
            T_vapor_calc, yE_vapor_calc,
            p_top_calc, p_sump,
            FIXED_FEED_FLOW_KGMOL_PER_S, feed_xE, feed_temperature_k,
            u["R_flow"], u["D_flow"], u["B_flow"],
            u["steam_kg_h"], u["cooling_kg_h"],
            float(col._cooling_water_temperature_c),
            direct_vapor_bypass=None,
        )
        dM_tray, dnE_tray, dU_tray, dM_drum, dnE_drum, dU_drum, \
            dM_sump, dnE_sump, dU_sump, \
            dN_vapor, dnE_vapor, dU_vapor = rhs

        # V_calculated（由 Q_R 真实机理求得）
        V_calculated = float(col._V_boil_internal)

        # ===== 拼接 51 个残差（修复指令 §8.4 + §8.6 缩放） =====
        residuals = np.zeros(N_UNKNOWN, dtype=np.float64)
        ridx = 0

        # 45 个状态导数残差
        # dM_tray[12] / 1e-8
        for i in range(N_TRAYS):
            residuals[ridx] = float(dM_tray[i]) / 1e-8; ridx += 1
        # dnE_tray[12] / 1e-9
        for i in range(N_TRAYS):
            residuals[ridx] = float(dnE_tray[i]) / 1e-9; ridx += 1
        # dU_tray[12] / 1e-3
        for i in range(N_TRAYS):
            residuals[ridx] = float(dU_tray[i]) / 1e-3; ridx += 1
        # dM_drum, dM_sump / 1e-8
        residuals[ridx] = float(dM_drum) / 1e-8; ridx += 1
        # dnE_drum, dnE_sump / 1e-9
        residuals[ridx] = float(dnE_drum) / 1e-9; ridx += 1
        # dU_drum, dU_sump / 1e-3
        residuals[ridx] = float(dU_drum) / 1e-3; ridx += 1
        # dM_sump / 1e-8
        residuals[ridx] = float(dM_sump) / 1e-8; ridx += 1
        # dnE_sump / 1e-9
        residuals[ridx] = float(dnE_sump) / 1e-9; ridx += 1
        # dU_sump / 1e-3
        residuals[ridx] = float(dU_sump) / 1e-3; ridx += 1
        # dN_vapor / 1e-9
        residuals[ridx] = float(dN_vapor) / 1e-9; ridx += 1
        # dnE_vapor / 1e-9
        residuals[ridx] = float(dnE_vapor) / 1e-9; ridx += 1
        # dU_vapor / 1e-3
        residuals[ridx] = float(dU_vapor) / 1e-3; ridx += 1

        # 6 个等式约束残差
        # V_trial - V_calculated / 1e-9
        residuals[ridx] = (V_trial - V_calculated) / 1e-9; ridx += 1

        # drum_level_pct - 50 / 0.1
        drum_level_pct = u["M_drum"] / col._m_drum_max * 100.0
        residuals[ridx] = (drum_level_pct - TARGET_DRUM_LEVEL_PCT) / 0.1; ridx += 1

        # sump_level_pct - 50 / 0.1
        sump_level_pct = u["M_sump"] / col._m_sump_max * 100.0
        residuals[ridx] = (sump_level_pct - TARGET_SUMP_LEVEL_PCT) / 0.1; ridx += 1

        # P_top - 101.325 / 0.10
        residuals[ridx] = (u["P_top"] - TARGET_TOP_PRESSURE_KPA) / 0.10; ridx += 1

        # top_ethanol_wt - 0.85 / 0.003
        xD_mol = u["xE_drum"]
        top_ethanol_wt = ethanol_mole_fraction_to_mass_fraction(xD_mol)
        residuals[ridx] = (top_ethanol_wt - TARGET_TOP_ETHANOL_WT) / 0.003; ridx += 1

        # bottom_ethanol_wt - 0.015 / 0.001
        xB_mol = u["xE_sump"]
        bottom_ethanol_wt = ethanol_mole_fraction_to_mass_fraction(xB_mol)
        residuals[ridx] = (bottom_ethanol_wt - TARGET_BOTTOM_ETHANOL_WT) / 0.001; ridx += 1

        assert ridx == N_UNKNOWN, f"残差索引错误: {ridx} != {N_UNKNOWN}"
        return residuals

    except (ValueError, RuntimeError, FloatingPointError) as e:
        # 修复指令 §8.9：只捕获已知数值异常，返回大残差
        return np.full(N_UNKNOWN, 1e6, dtype=np.float64)


# ====================================================================
# 求解器上下界和初猜（修复指令 §8.7 + §8.8）
# ====================================================================
def build_solver_bounds(
    col: ETHANOL_WATER_DISTILLATION,
) -> Tuple[np.ndarray, np.ndarray]:
    """构造 51 维变量的上下界。"""
    lower = np.zeros(N_UNKNOWN, dtype=np.float64)
    upper = np.zeros(N_UNKNOWN, dtype=np.float64)
    idx = 0

    # M_tray[12]: 0.2*m_nom ~ 3.0*m_nom
    m_nom = col._m_tray_nom
    for _ in range(N_TRAYS):
        lower[idx] = 0.2 * m_nom; upper[idx] = 3.0 * m_nom; idx += 1
    # xE_tray[12]: 1e-8 ~ 0.999999
    for _ in range(N_TRAYS):
        lower[idx] = 1e-8; upper[idx] = 0.999999; idx += 1
    # T_tray[12]: 280 ~ 420 K
    for _ in range(N_TRAYS):
        lower[idx] = 280.0; upper[idx] = 420.0; idx += 1
    # M_drum: 0.10*m_drum_100pct ~ 0.90*m_drum_100pct
    m_drum_max = col._m_drum_max
    lower[idx] = 0.10 * m_drum_max; upper[idx] = 0.90 * m_drum_max; idx += 1
    # xE_drum: 1e-8 ~ 0.999999
    lower[idx] = 1e-8; upper[idx] = 0.999999; idx += 1
    # T_drum: 280 ~ 420 K
    lower[idx] = 280.0; upper[idx] = 420.0; idx += 1
    # M_sump: 0.10*m_sump_100pct ~ 0.90*m_sump_100pct
    m_sump_max = col._m_sump_max
    lower[idx] = 0.10 * m_sump_max; upper[idx] = 0.90 * m_sump_max; idx += 1
    # xE_sump: 1e-8 ~ 0.999999
    lower[idx] = 1e-8; upper[idx] = 0.999999; idx += 1
    # T_sump: 280 ~ 420 K
    lower[idx] = 280.0; upper[idx] = 420.0; idx += 1
    # P_top: 70.1 ~ 130 kPa(a)
    lower[idx] = 70.1; upper[idx] = 130.0; idx += 1
    # yE_vapor: 1e-8 ~ 0.999999
    lower[idx] = 1e-8; upper[idx] = 0.999999; idx += 1
    # T_vapor: 280 ~ 420 K
    lower[idx] = 280.0; upper[idx] = 420.0; idx += 1
    # R: 1e-7 ~ 0.0015
    lower[idx] = 1e-7; upper[idx] = 0.0015; idx += 1
    # D: 1e-7 ~ 0.0015
    lower[idx] = 1e-7; upper[idx] = 0.0015; idx += 1
    # B: 1e-7 ~ 0.0030
    lower[idx] = 1e-7; upper[idx] = 0.0030; idx += 1
    # steam: 0.1 ~ 100 kg/h
    lower[idx] = 0.1; upper[idx] = 100.0; idx += 1
    # cooling: 1 ~ 7000 kg/h
    lower[idx] = 1.0; upper[idx] = 7000.0; idx += 1
    # V_trial: 1e-8 ~ 0.0030
    lower[idx] = 1e-8; upper[idx] = 0.0030; idx += 1

    assert idx == N_UNKNOWN, f"上下界索引错误: {idx} != {N_UNKNOWN}"
    return lower, upper


def build_initial_guess(
    col: ETHANOL_WATER_DISTILLATION,
) -> Tuple[np.ndarray, OperatingInputs, float]:
    """从 WARM_GUESS 状态构造初猜。"""
    op = OperatingInputs(
        feed_flow_kgmol_per_s=FIXED_FEED_FLOW_KGMOL_PER_S,
        reflux_flow_kgmol_per_s=float(col.reflux_flow_kgmol_per_s),
        distillate_flow_kgmol_per_s=float(col.distillate_flow_kgmol_per_s),
        bottoms_flow_kgmol_per_s=float(col.bottoms_flow_kgmol_per_s),
        steam_flow_kg_h=INITIAL_STEAM_FLOW_KG_H,
        cooling_flow_kg_h=INITIAL_COOLING_FLOW_KG_H,
    )
    V_trial = INITIAL_VAPOR_BOILUP_GUESS_KGMOL_PER_S
    z0 = pack_unknowns(col, op, V_trial)
    return z0, op, V_trial


# ====================================================================
# 求解结果安装（修复指令 §9）
# ====================================================================
def install_steady_solution(
    col: ETHANOL_WATER_DISTILLATION,
    result_vector: np.ndarray,
) -> OperatingInputs:
    """
    将求解结果安装到模型并返回 OperatingInputs。

    必须按 §9 顺序：
    1. M/x/T → M/nE/U 写入模型
    2. 气相 N/nE/U 写入模型
    3. _last_feed_flow / _last_reflux_flow / _last_distillate_flow / _last_bottoms_flow
    4. _last_steam_flow_kg_per_h / _last_cooling_flow_kg_per_h
    5. _V_boil_internal 初值
    6. _compute_algebraic() 更新派生状态
    7. _publish_scalar_attributes()
    8. 返回 OperatingInputs
    """
    u = unpack_unknowns(result_vector)

    # 1) 塔板/回流罐/塔釜状态
    col._M_tray = np.array(u["M_tray"], dtype=np.float64).copy()
    col._nE_tray = np.array(u["nE_tray"], dtype=np.float64).copy()
    col._U_tray = np.array(u["U_tray"], dtype=np.float64).copy()
    col._M_drum = float(u["M_drum"])
    col._nE_drum = float(u["nE_drum"])
    col._U_drum = float(u["U_drum"])
    col._M_sump = float(u["M_sump"])
    col._nE_sump = float(u["nE_sump"])
    col._U_sump = float(u["U_sump"])

    # 2) 气相状态（修复指令 §8.3）
    P_top = max(u["P_top"], 1e-6)
    T_vapor = max(u["T_vapor"], 250.0)
    yE_vapor = max(0.0, min(0.999999, u["yE_vapor"]))
    N_vapor = P_top * col._vapor_volume_m3 / (R_UNIVERSAL_KPA_M3_PER_KMOL_K * T_vapor)
    nE_vapor = N_vapor * yE_vapor
    U_vapor = N_vapor * vapor_internal_energy_kj_per_kmol(yE_vapor, T_vapor)
    col._N_vapor = float(N_vapor)
    col._nE_vapor = float(nE_vapor)
    col._U_vapor = float(U_vapor)

    # 3) 过程流量
    col._last_feed_flow = FIXED_FEED_FLOW_KGMOL_PER_S
    col._last_reflux_flow = float(u["R_flow"])
    col._last_distillate_flow = float(u["D_flow"])
    col._last_bottoms_flow = float(u["B_flow"])

    # 4) 公用工程流量
    col._last_steam_flow_kg_per_h = float(u["steam_kg_h"])
    col._last_cooling_flow_kg_per_h = float(u["cooling_kg_h"])

    # 5) V_boil_internal 初值（求解器收敛后由 _calculate_rhs 内部一致）
    col._V_boil_internal = float(u["V_trial"])
    col._V_kgmol_per_s = float(u["V_trial"])
    col._last_vapor_boilup = float(u["V_trial"])

    # 6) 重新调用 _compute_algebraic 更新派生状态
    algebraic = col._compute_algebraic(
        col._M_tray, col._nE_tray, col._U_tray,
        col._M_drum, col._nE_drum, col._U_drum,
        col._M_sump, col._nE_sump, col._U_sump,
        col._N_vapor, col._nE_vapor, col._U_vapor,
        col._V_boil_internal,
    )
    (
        T_tray, yE_tray, T_drum, T_sump, yE_sump,
        p_top, pressure_kpa, p_sump,
        T_vapor_avg, yE_vapor_calc, T_vapor_calc,
    ) = algebraic
    col._T_tray = T_tray.copy()
    col._yE_tray = yE_tray.copy()
    col._T_drum = float(T_drum)
    col._T_sump = float(T_sump)
    col._yE_sump = float(yE_sump)
    col._p_top_kpa = float(p_top)
    col._p_sump_kpa = float(p_sump)
    col._pressure_kpa = pressure_kpa.copy()
    col._T_vapor_avg = float(T_vapor_avg)
    col._yE_vapor = float(yE_vapor_calc)
    col._T_vapor = float(T_vapor_calc)

    # 7) 发布对外位号
    col._publish_scalar_attributes()

    # 8) 返回不可变 OperatingInputs
    return OperatingInputs(
        feed_flow_kgmol_per_s=FIXED_FEED_FLOW_KGMOL_PER_S,
        reflux_flow_kgmol_per_s=float(u["R_flow"]),
        distillate_flow_kgmol_per_s=float(u["D_flow"]),
        bottoms_flow_kgmol_per_s=float(u["B_flow"]),
        steam_flow_kg_h=float(u["steam_kg_h"]),
        cooling_flow_kg_h=float(u["cooling_kg_h"]),
    )


# ====================================================================
# 收敛指标计算（修复指令 §10.2）
# ====================================================================
def compute_convergence_metrics(
    col: ETHANOL_WATER_DISTILLATION,
    previous: Optional[StateSnapshot],
    dt: float,
) -> Dict[str, float]:
    """计算收敛指标（包含状态导数，修复指令 §10.2-§10.3）。"""
    metrics: Dict[str, float] = {
        "drum_level_pct": float(col.raw_reflux_drum_level_pct),
        "sump_level_pct": float(col.raw_reboiler_level_pct),
        "top_pressure_kpa": float(col.top_pressure_kpa),
        "top_ethanol_wt": float(col.top_ethanol_wt),
        "bottom_ethanol_wt": float(col.bottom_ethanol_wt),
        "ethanol_recovery_pct": 0.0,
        "mass_residual_rel": 0.0,
        "ethanol_residual_rel": 0.0,
        "energy_residual_rel": 0.0,
    }

    feed_ethanol_kgh = col.feed_flow_kg_h * col._feed_ethanol_wt
    if feed_ethanol_kgh > 1e-9:
        metrics["ethanol_recovery_pct"] = (
            col.distillate_flow_kg_h * col.top_ethanol_wt
            / feed_ethanol_kgh
            * 100.0
        )
    if col.feed_flow_kg_h > 1e-9:
        metrics["mass_residual_rel"] = abs(col.mass_closure_residual_kg_h) / col.feed_flow_kg_h
        metrics["ethanol_residual_rel"] = (
            abs(col.ethanol_closure_residual_kg_h)
            / max(feed_ethanol_kgh, 1e-9)
        )
    if abs(col.reboiler_duty_kw) > 1e-9:
        metrics["energy_residual_rel"] = (
            abs(col.energy_closure_residual_kw) / abs(col.reboiler_duty_kw)
        )

    # 状态导数（修复指令 §10.2）
    if previous is not None and dt > 0.0:
        metrics["max_abs_dM_tray_dt"] = float(
            np.max(np.abs(np.array(col._M_tray) - previous.M_tray)) / dt
        )
        metrics["max_abs_dnE_tray_dt"] = float(
            np.max(np.abs(np.array(col._nE_tray) - previous.nE_tray)) / dt
        )
        metrics["abs_dM_drum_dt"] = abs(float(col._M_drum) - previous.M_drum) / dt
        metrics["abs_dM_sump_dt"] = abs(float(col._M_sump) - previous.M_sump) / dt
        metrics["abs_dN_vapor_dt"] = abs(float(col._N_vapor) - previous.N_vapor) / dt
        metrics["abs_dP_top_dt"] = abs(float(col._p_top_kpa) - previous.P_top) / dt
        # 所有温度导数取最大
        dT_tray = np.max(np.abs(np.array(col._T_tray) - previous.T_tray)) / dt
        dT_drum = abs(float(col._T_drum) - previous.T_drum) / dt
        dT_sump = abs(float(col._T_sump) - previous.T_sump) / dt
        dT_vapor = abs(float(col._T_vapor) - previous.T_vapor) / dt
        metrics["max_abs_dT_dt"] = float(max(dT_tray, dT_drum, dT_sump, dT_vapor))
    else:
        # 第一周期无前态，导数设为 NaN 以便 check_convergence 返回 False
        metrics["max_abs_dM_tray_dt"] = float("nan")
        metrics["max_abs_dnE_tray_dt"] = float("nan")
        metrics["abs_dM_drum_dt"] = float("nan")
        metrics["abs_dM_sump_dt"] = float("nan")
        metrics["abs_dN_vapor_dt"] = float("nan")
        metrics["abs_dP_top_dt"] = float("nan")
        metrics["max_abs_dT_dt"] = float("nan")

    return metrics


def check_convergence(metrics: Dict[str, float]) -> bool:
    """严格落实 todo/5.md §9.4 全部门槛（修复指令 §10.3）。

    修复指令 §6：在任何阈值比较前先检查字段存在性和有限性。
    NaN > threshold 结果为 False，会错误地绕过门禁，因此必须显式拒绝。
    """
    required_metrics = [
        "max_abs_dM_tray_dt",
        "max_abs_dnE_tray_dt",
        "abs_dM_drum_dt",
        "abs_dM_sump_dt",
        "abs_dN_vapor_dt",
        "abs_dP_top_dt",
        "max_abs_dT_dt",
        "drum_level_pct",
        "sump_level_pct",
        "top_pressure_kpa",
        "top_ethanol_wt",
        "bottom_ethanol_wt",
        "ethanol_recovery_pct",
        "mass_residual_rel",
        "ethanol_residual_rel",
        "energy_residual_rel",
    ]

    # §6.1：字段存在 + 可转 float + 有限性
    values: Dict[str, float] = {}
    for key in required_metrics:
        if key not in metrics:
            return False
        try:
            value = float(metrics[key])
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        values[key] = value

    # 状态导数门槛
    if values["max_abs_dM_tray_dt"] > 1e-8:
        return False
    if values["max_abs_dnE_tray_dt"] > 1e-9:
        return False
    if values["abs_dM_drum_dt"] > 1e-8:
        return False
    if values["abs_dM_sump_dt"] > 1e-8:
        return False
    if values["abs_dN_vapor_dt"] > 1e-9:
        return False
    if values["abs_dP_top_dt"] > 1e-4:
        return False
    if values["max_abs_dT_dt"] > 1e-4:
        return False
    # 液位范围
    if not (47.0 <= values["drum_level_pct"] <= 53.0):
        return False
    if not (47.0 <= values["sump_level_pct"] <= 53.0):
        return False
    # 压力
    if abs(values["top_pressure_kpa"] - 101.325) > 0.10:
        return False
    # 组成
    if not (0.82 <= values["top_ethanol_wt"] <= 0.88):
        return False
    if not (0.010 <= values["bottom_ethanol_wt"] <= 0.020):
        return False
    # 回收率
    if values["ethanol_recovery_pct"] < 95.0:
        return False
    # 闭合残差
    if values["mass_residual_rel"] > 0.001:
        return False
    if values["ethanol_residual_rel"] > 0.002:
        return False
    if values["energy_residual_rel"] > 0.01:
        return False
    return True


# ====================================================================
# 求解器结果门禁（修复指令 §5）
# ====================================================================
def validate_solver_result(result: Any) -> None:
    """加强 least_squares 求解结果门禁。

    正状态只表示求解器满足某个停止条件，不代表残差一定合格。
    必须独立检查：
        1. status > 0
        2. 解向量 x 全部有限
        3. 残差向量 fun 全部有限
        4. 最大缩放残差 <= 1.0
    """
    residuals = np.asarray(result.fun, dtype=np.float64)
    x = np.asarray(result.x, dtype=np.float64)

    if result.status <= 0:
        raise ReferenceStateGenerationError(
            f"least_squares 求解失败（status={result.status}）: {result.message}\n"
            f"  nfev={result.nfev}, cost={result.cost}, optimality={result.optimality}\n"
            f"  max residual={float(np.max(np.abs(residuals))) if residuals.size > 0 else 'NaN'}"
        )

    if x.size == 0 or not np.all(np.isfinite(x)):
        raise ReferenceStateGenerationError(
            f"least_squares 解向量包含 NaN/Inf\n"
            f"  status={result.status}, message={result.message}\n"
            f"  nfev={result.nfev}, cost={result.cost}, optimality={result.optimality}"
        )

    if residuals.size == 0 or not np.all(np.isfinite(residuals)):
        raise ReferenceStateGenerationError(
            f"least_squares 残差包含 NaN/Inf\n"
            f"  status={result.status}, message={result.message}\n"
            f"  nfev={result.nfev}, cost={result.cost}, optimality={result.optimality}"
        )

    max_scaled_residual = float(np.max(np.abs(residuals)))
    if max_scaled_residual > 1.0:
        raise ReferenceStateGenerationError(
            f"least_squares 最大缩放残差超限: {max_scaled_residual} > 1.0\n"
            f"  status={result.status}, message={result.message}\n"
            f"  nfev={result.nfev}, cost={result.cost}, optimality={result.optimality}"
        )


# ====================================================================
# 阀位反算（修复指令 §12.1）
# ====================================================================
def compute_valve_pct_from_flow(
    col: ETHANOL_WATER_DISTILLATION,
    op: OperatingInputs,
) -> Dict[str, float]:
    """根据求解结果对应的当前组成反算阀位。"""
    xD_mol = float(col._nE_drum / col._M_drum) if col._M_drum > 1e-15 else 0.0
    xD_mol = max(0.0, min(1.0, xD_mol))
    xB_mol = float(col._nE_sump / col._M_sump) if col._M_sump > 1e-15 else 0.0
    xB_mol = max(0.0, min(1.0, xB_mol))
    xF_mol = ethanol_mass_fraction_to_mole_fraction(col._feed_ethanol_wt)

    from components.programs.ethanol_water_distillation import (
        _mixture_molecular_weight, _kgmols_to_kgh,
    )
    feed_mass_kgh = _kgmols_to_kgh(op.feed_flow_kgmol_per_s, _mixture_molecular_weight(xF_mol))
    reflux_mass_kgh = _kgmols_to_kgh(op.reflux_flow_kgmol_per_s, _mixture_molecular_weight(xD_mol))
    distillate_mass_kgh = _kgmols_to_kgh(op.distillate_flow_kgmol_per_s, _mixture_molecular_weight(xD_mol))
    bottoms_mass_kgh = _kgmols_to_kgh(op.bottoms_flow_kgmol_per_s, _mixture_molecular_weight(xB_mol))

    max_flows = col._valve_max_flow_kg_per_h

    def _pct(flow_kg_h: float, max_kg_h: float, valve_name: str) -> float:
        if max_kg_h <= 0:
            return 0.0
        ratio = max(0.0, min(1.0, flow_kg_h / max_kg_h))
        valve = col._valves[valve_name]
        return valve.opening_from_flow_fraction(ratio)

    return {
        "feed_valve_pct": _pct(feed_mass_kgh, max_flows["feed"], "feed"),
        "reflux_valve_pct": _pct(reflux_mass_kgh, max_flows["reflux"], "reflux"),
        "distillate_valve_pct": _pct(distillate_mass_kgh, max_flows["distillate"], "distillate"),
        "bottoms_valve_pct": _pct(bottoms_mass_kgh, max_flows["bottoms"], "bottoms"),
        "steam_valve_pct": _pct(op.steam_flow_kg_h, max_flows["steam"], "steam"),
        "cooling_valve_pct": _pct(op.cooling_flow_kg_h, max_flows["cooling"], "cooling"),
    }


# ====================================================================
# 单步模式等价性门禁（修复指令 §12）
# ====================================================================
def verify_mode_equivalence(
    col: ETHANOL_WATER_DISTILLATION,
    op: OperatingInputs,
    valve_cmds: Dict[str, float],
) -> Tuple[bool, str]:
    """验证直接实际流量模式与阀位模式单步等价。"""
    state_before = col.save_state()

    direct_col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
    direct_col.load_state(copy.deepcopy(state_before))

    valve_col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
    valve_col.load_state(copy.deepcopy(state_before))

    # 同步阀门 command/actual 为反算值
    for key, pct in valve_cmds.items():
        valve_name = key.replace("_valve_pct", "")
        valve_col._valves[valve_name].command_pct = pct
        valve_col._valves[valve_name].actual_pct = pct

    # 各运行一个 cycle_time
    direct_col.execute(**{
        "feed_flow_kgmol_per_s": op.feed_flow_kgmol_per_s,
        "reflux_flow_kgmol_per_s": op.reflux_flow_kgmol_per_s,
        "distillate_flow_kgmol_per_s": op.distillate_flow_kgmol_per_s,
        "bottoms_flow_kgmol_per_s": op.bottoms_flow_kgmol_per_s,
        "steam_flow_kg_h": op.steam_flow_kg_h,
        "cooling_flow_kg_h": op.cooling_flow_kg_h,
    })
    valve_col.execute(**valve_cmds)

    # 比较实际流量
    rtol_flow = 1e-8
    atol_flow = 1e-10
    for attr in [
        "feed_flow_kg_h", "reflux_flow_kg_h", "distillate_flow_kg_h",
        "bottoms_flow_kg_h", "steam_flow_kg_h", "cooling_flow_kg_h",
    ]:
        v_direct = float(getattr(direct_col, attr))
        v_valve = float(getattr(valve_col, attr))
        rel = abs(v_direct - v_valve) / max(abs(v_direct), 1e-12)
        if not (rel < rtol_flow or abs(v_direct - v_valve) < atol_flow):
            return False, f"{attr} 不等价: direct={v_direct}, valve={v_valve}, rel={rel}"

    # 比较 V_boil/V_condense/Q_R/Q_C/P_top
    rtol_phys = 1e-7
    atol_phys = 1e-10
    for attr in [
        "_V_boil_internal", "_V_condense_internal",
        "_Q_R_kw", "_Q_C_kw", "_p_top_kpa",
    ]:
        v_direct = float(getattr(direct_col, attr))
        v_valve = float(getattr(valve_col, attr))
        rel = abs(v_direct - v_valve) / max(abs(v_direct), 1e-12)
        if not (rel < rtol_phys or abs(v_direct - v_valve) < atol_phys):
            return False, f"{attr} 不等价: direct={v_direct}, valve={v_valve}, rel={rel}"

    # 比较核心状态数组
    for attr in [
        "_M_tray", "_nE_tray", "_U_tray",
        "_M_drum", "_nE_drum", "_U_drum",
        "_M_sump", "_nE_sump", "_U_sump",
        "_N_vapor", "_nE_vapor", "_U_vapor",
    ]:
        v_direct = np.asarray(getattr(direct_col, attr), dtype=np.float64)
        v_valve = np.asarray(getattr(valve_col, attr), dtype=np.float64)
        if not np.allclose(v_direct, v_valve, rtol=rtol_phys, atol=atol_phys):
            return False, f"{attr} 不等价: max_diff={np.max(np.abs(v_direct - v_valve))}"

    return True, "模式等价性通过"


# ====================================================================
# 原子写盘（修复指令 §14）
# ====================================================================
def atomic_write_reference_state(
    output_path: Path,
    payload: Dict[str, Any],
) -> None:
    """原子写入参考稳态文件（修复指令 §14）。"""
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, output_path)
    except Exception:
        # 异常时清理 .tmp，但不删除旧正式文件
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


# ====================================================================
# 主生成流程
# ====================================================================
def generate_reference_state(
    output_path: str,
    verbose: bool = True,
    skip_long_validation: bool = False,
) -> Dict[str, Any]:
    """
    生成参考稳态。

    Args:
        output_path: 输出 JSON 路径
        verbose: 是否打印详细日志
        skip_long_validation: 跳过长稳态窗口和漂移验证（仅供 Agent 快速测试）。
            正式生成必须 False。

    Returns:
        收敛信息字典

    Raises:
        ReferenceStateGenerationError: 任何门禁失败
    """
    output_path_obj = Path(output_path)

    if verbose:
        print("=" * 70)
        print("乙醇—水精馏塔参考稳态生成器（修复指令 §4）")
        print("=" * 70)
        print()
        print("策略：scipy.optimize.least_squares 求一致稳态")
        print(f"  未知量维度：{N_UNKNOWN}")
        print("  direct_vapor_bypass: 始终 None（共享植物物理方程）")
        print(f"  长稳态验证: {'跳过（Agent 模式）' if skip_long_validation else '启用'}")
        print()

    t_start = time.time()

    # 构造 WARM_GUESS 模型
    col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
    cycle_time = float(REFERENCE_PARAMS["cycle_time"])

    # ===== 阶段 1：构造初猜 =====
    if verbose:
        print("阶段 1：构造 WARM_GUESS 初猜")
        print("-" * 70)

    z0, op_init, V_trial_init = build_initial_guess(col)
    lower, upper = build_solver_bounds(col)

    if verbose:
        print(f"  初猜向量维度: {len(z0)}")
        print(f"  F={FIXED_FEED_FLOW_KGMOL_PER_S:.8f} kmol/s (固定)")
        print(f"  R={op_init.reflux_flow_kgmol_per_s:.6e}, D={op_init.distillate_flow_kgmol_per_s:.6e}")
        print(f"  B={op_init.bottoms_flow_kgmol_per_s:.6e}")
        print(f"  steam={op_init.steam_flow_kg_h:.2f} kg/h, cooling={op_init.cooling_flow_kg_h:.2f} kg/h")
        print(f"  V_trial={V_trial_init:.6e} kmol/s")
        print()

    # ===== 阶段 2：least_squares 求解 =====
    if verbose:
        print("阶段 2：scipy.optimize.least_squares 求解")
        print("-" * 70)

    try:
        result = least_squares(
            fun=evaluate_steady_residual,
            x0=z0,
            bounds=(lower, upper),
            method="trf",
            x_scale="jac",
            loss="linear",
            ftol=1e-10,
            xtol=1e-10,
            gtol=1e-10,
            max_nfev=2000,
            verbose=2 if verbose else 0,
            args=(col,),
        )
    except Exception as e:
        raise ReferenceStateGenerationError(
            f"least_squares 求解器抛出异常: {e}"
        ) from e

    t_solver = time.time() - t_start
    if verbose:
        print()
        print(f"  求解耗时: {t_solver:.1f} s")
        print(f"  status: {result.status}")
        print(f"  message: {result.message}")
        print(f"  nfev: {result.nfev}")
        print(f"  cost: {result.cost:.6e}")
        print(f"  optimality: {result.optimality:.6e}")
        print(f"  max residual: {np.max(np.abs(result.fun)):.6e}")
        print()

    # 检查求解是否成功
    validate_solver_result(result)

    # ===== 阶段 3：安装求解结果 =====
    if verbose:
        print("阶段 3：安装求解结果")
        print("-" * 70)

    op = install_steady_solution(col, result.x)

    if verbose:
        print(f"  R={op.reflux_flow_kgmol_per_s:.6e} kmol/s")
        print(f"  D={op.distillate_flow_kgmol_per_s:.6e} kmol/s")
        print(f"  B={op.bottoms_flow_kgmol_per_s:.6e} kmol/s")
        print(f"  steam={op.steam_flow_kg_h:.4f} kg/h")
        print(f"  cooling={op.cooling_flow_kg_h:.4f} kg/h")
        print(f"  V_boil_internal={col._V_boil_internal:.6e} kmol/s")
        print(f"  P_top={col._p_top_kpa:.4f} kPa")
        print(f"  drum_level={col.raw_reflux_drum_level_pct:.2f}%")
        print(f"  sump_level={col.raw_reboiler_level_pct:.2f}%")
        print(f"  xD_wt={col.top_ethanol_wt:.4f}")
        print(f"  xB_wt={col.bottom_ethanol_wt:.4f}")
        print()

    # ===== 阶段 4：直接实际流量动态验证（短） =====
    if verbose:
        print("阶段 4：直接实际流量动态验证（短）")
        print("-" * 70)

    # 用同一 op 跑 3 周期，验证状态有限且不立即崩溃
    for cycle in range(3):
        prev = capture_state_snapshot(col)
        col.execute(
            feed_flow_kgmol_per_s=op.feed_flow_kgmol_per_s,
            reflux_flow_kgmol_per_s=op.reflux_flow_kgmol_per_s,
            distillate_flow_kgmol_per_s=op.distillate_flow_kgmol_per_s,
            bottoms_flow_kgmol_per_s=op.bottoms_flow_kgmol_per_s,
            steam_flow_kg_h=op.steam_flow_kg_h,
            cooling_flow_kg_h=op.cooling_flow_kg_h,
        )
        m = compute_convergence_metrics(col, prev, cycle_time)
        if verbose:
            print(
                f"  cycle {cycle} | P={m['top_pressure_kpa']:7.3f} | "
                f"drum={m['drum_level_pct']:5.1f}% sump={m['sump_level_pct']:5.1f}% | "
                f"xD={m['top_ethanol_wt']:.4f} xB={m['bottom_ethanol_wt']:.4f} | "
                f"dM/dt={m.get('max_abs_dM_tray_dt', float('nan')):.2e}"
            )

    if not math.isfinite(col._p_top_kpa) or not math.isfinite(col._M_drum):
        raise ReferenceStateGenerationError(
            "直接实际流量动态验证：状态非有限，求解结果可能不正确"
        )
    if verbose:
        print()

    # ===== 阶段 5：阀位反算 + 模式等价性验证 =====
    if verbose:
        print("阶段 5：阀位反算 + 模式等价性验证")
        print("-" * 70)

    valve_cmds = compute_valve_pct_from_flow(col, op)
    if verbose:
        print(f"  反算阀位: {valve_cmds}")
        print()

    # 恢复到求解结果状态（阶段 4 已运行 3 周期，重新安装求解结果）
    install_steady_solution(col, result.x)

    eq_pass, eq_msg = verify_mode_equivalence(col, op, valve_cmds)
    if verbose:
        print(f"  模式等价性: {'✓ 通过' if eq_pass else '✗ 未通过'}")
        if not eq_pass:
            print(f"  失败原因: {eq_msg}")
        print()

    if not eq_pass:
        raise ReferenceStateGenerationError(f"模式等价性门禁失败: {eq_msg}")

    # ===== 阶段 6：连续稳态窗口（1800 s = 3600 cycles）=====
    # 修复指令 §4.1：skip_long_validation 不再"假装通过"
    convergence_window_required = 3600  # 1800 s @ 0.5 s
    convergence_window_count = 0
    final_metrics: Dict[str, float] = {}

    if skip_long_validation:
        if verbose:
            print("阶段 6：跳过连续稳态窗口（快速诊断模式，不计入通过）")
            print()
        convergence_window_count = 0
    else:
        if verbose:
            print(f"阶段 6：连续稳态窗口 {convergence_window_required} 周期（1800 s）")
            print("-" * 70)

        # 恢复到求解结果状态
        install_steady_solution(col, result.x)

        for cycle in range(convergence_window_required):
            prev = capture_state_snapshot(col)
            col.execute(
                feed_flow_kgmol_per_s=op.feed_flow_kgmol_per_s,
                reflux_flow_kgmol_per_s=op.reflux_flow_kgmol_per_s,
                distillate_flow_kgmol_per_s=op.distillate_flow_kgmol_per_s,
                bottoms_flow_kgmol_per_s=op.bottoms_flow_kgmol_per_s,
                steam_flow_kg_h=op.steam_flow_kg_h,
                cooling_flow_kg_h=op.cooling_flow_kg_h,
            )
            final_metrics = compute_convergence_metrics(col, prev, cycle_time)
            if check_convergence(final_metrics):
                convergence_window_count += 1
            else:
                convergence_window_count = 0

            if verbose and (cycle % 500 == 0 or cycle == convergence_window_required - 1):
                print(
                    f"  cycle {cycle:5d} | P={final_metrics['top_pressure_kpa']:7.3f} | "
                    f"drum={final_metrics['drum_level_pct']:5.1f}% sump={final_metrics['sump_level_pct']:5.1f}% | "
                    f"xD={final_metrics['top_ethanol_wt']:.4f} xB={final_metrics['bottom_ethanol_wt']:.4f} | "
                    f"dM/dt={final_metrics.get('max_abs_dM_tray_dt', float('nan')):.2e} | "
                    f"win={convergence_window_count}/{convergence_window_required}"
                )

        if verbose:
            print(f"\n阶段 6 完成: 收敛窗口 {convergence_window_count}/{convergence_window_required}")
            print()

        # 修复指令 §10.4：连续窗口必须是硬门禁
        if convergence_window_count < convergence_window_required:
            raise ReferenceStateGenerationError(
                f"未满足连续稳态窗口（{convergence_window_count}/{convergence_window_required}），"
                f"禁止进入阀位验证和正式写盘\n"
                f"最后周期指标: {final_metrics}"
            )

    # ===== 阶段 7：阀位模式漂移验证（3600 s = 7200 cycles）=====
    # 修复指令 §4.1：skip_long_validation 不再"假装通过"
    drift_pass = False
    drift: Dict[str, float] = {}

    if skip_long_validation:
        if verbose:
            print("阶段 7：跳过阀位漂移验证（快速诊断模式，drift_pass=False）")
            print()
    else:
        if verbose:
            print("阶段 7：阀位模式漂移验证 7200 周期（3600 s）")
            print("-" * 70)

        # 恢复到求解结果状态，并设置阀门为反算值
        install_steady_solution(col, result.x)
        for key, pct in valve_cmds.items():
            valve_name = key.replace("_valve_pct", "")
            col._valves[valve_name].command_pct = pct
            col._valves[valve_name].actual_pct = pct

        # 记录初始状态
        p_init = float(col._p_top_kpa)
        drum_init = float(col.raw_reflux_drum_level_pct)
        sump_init = float(col.raw_reboiler_level_pct)
        t_top_init = float(col._T_tray[0] - 273.15)
        t_bot_init = float(col._T_sump - 273.15)
        xD_init = float(col.top_ethanol_wt)
        xB_init = float(col.bottom_ethanol_wt)

        for cycle in range(7200):
            col.execute(**valve_cmds)
            if verbose and cycle % 1000 == 0:
                m = compute_convergence_metrics(col, None, cycle_time)
                print(
                    f"  cycle {cycle:5d} | P={m['top_pressure_kpa']:7.3f} | "
                    f"drum={m['drum_level_pct']:5.1f}% sump={m['sump_level_pct']:5.1f}% | "
                    f"xD={m['top_ethanol_wt']:.4f} xB={m['bottom_ethanol_wt']:.4f}"
                )

        p_final = float(col._p_top_kpa)
        drum_final = float(col.raw_reflux_drum_level_pct)
        sump_final = float(col.raw_reboiler_level_pct)
        t_top_final = float(col._T_tray[0] - 273.15)
        t_bot_final = float(col._T_sump - 273.15)
        xD_final = float(col.top_ethanol_wt)
        xB_final = float(col.bottom_ethanol_wt)

        drift = {
            "pressure_drift_kpa": abs(p_final - p_init),
            "drum_level_drift_pct": abs(drum_final - drum_init),
            "sump_level_drift_pct": abs(sump_final - sump_init),
            "top_temp_drift_c": abs(t_top_final - t_top_init),
            "bottom_temp_drift_c": abs(t_bot_final - t_bot_init),
            "top_x_drift": abs(xD_final - xD_init),
            "bottom_x_drift": abs(xB_final - xB_init),
        }

        if verbose:
            print(f"\n  漂移指标:")
            print(f"    压力:     {drift['pressure_drift_kpa']:.4f} kPa (限 0.10)")
            print(f"    回流罐:   {drift['drum_level_drift_pct']:.4f} % (限 1.0)")
            print(f"    塔釜:     {drift['sump_level_drift_pct']:.4f} % (限 1.0)")
            print(f"    塔顶温度: {drift['top_temp_drift_c']:.4f} °C (限 0.20)")
            print(f"    塔底温度: {drift['bottom_temp_drift_c']:.4f} °C (限 0.20)")
            print(f"    塔顶浓度: {drift['top_x_drift']:.5f} (限 0.003)")
            print(f"    塔底浓度: {drift['bottom_x_drift']:.5f} (限 0.001)")

        drift_pass = (
            drift["pressure_drift_kpa"] <= 0.10
            and drift["drum_level_drift_pct"] <= 1.0
            and drift["sump_level_drift_pct"] <= 1.0
            and drift["top_temp_drift_c"] <= 0.20
            and drift["bottom_temp_drift_c"] <= 0.20
            and drift["top_x_drift"] <= 0.003
            and drift["bottom_x_drift"] <= 0.001
        )

        if verbose:
            print(f"  漂移验收: {'✓ 通过' if drift_pass else '✗ 未通过'}")
            print()

        if not drift_pass:
            raise ReferenceStateGenerationError(
                f"阀位模式漂移门禁失败: {drift}"
            )

    # 修复指令 §4.2：快速模式不得写参考状态文件
    if skip_long_validation:
        if verbose:
            print("阶段 8：跳过原子写盘（快速诊断模式，passed=False）")
            print()
        return {
            "passed": False,
            "validation_skipped": True,
            "solver_passed": True,
            "mode_equivalence_passed": bool(eq_pass),
            "convergence_window_cycles": int(convergence_window_count),
            "drift_passed": bool(drift_pass),
            "final_F_kgmol_per_s": float(op.feed_flow_kgmol_per_s),
            "final_D_kgmol_per_s": float(op.distillate_flow_kgmol_per_s),
            "final_B_kgmol_per_s": float(op.bottoms_flow_kgmol_per_s),
            "final_R_kgmol_per_s": float(op.reflux_flow_kgmol_per_s),
            "final_steam_kg_h": float(op.steam_flow_kg_h),
            "final_cooling_kg_h": float(op.cooling_flow_kg_h),
            "final_reflux_ratio": float(
                op.reflux_flow_kgmol_per_s / max(op.distillate_flow_kgmol_per_s, 1e-15)
            ),
        }

    # ===== 阶段 8：原子写入正式 JSON =====
    if verbose:
        print("阶段 8：原子写入正式 JSON")
        print("-" * 70)

    # 恢复到求解结果状态用于保存
    install_steady_solution(col, result.x)
    state = col._get_full_state_dict()

    convergence_pass = bool(
        convergence_window_count >= convergence_window_required
        and eq_pass
        and drift_pass
    )

    state["metadata"] = {
        "model_name": "ETHANOL_WATER_DISTILLATION",
        "description": "Ethanol-water distillation reference steady state (auto-generated)",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generation_tool": "tools/generate_ethanol_water_reference_state.py",
        "generation_cycle_time_s": REFERENCE_PARAMS["cycle_time"],
        "generation_internal_step_s": REFERENCE_PARAMS["max_internal_step"],
        "thermo_version": "antoine_nrtl_arce_srnl_v1",
        "generation_method": "steady_rhs_least_squares_then_dynamic_validation",
        "used_direct_vapor_bypass": False,
        "solver": "scipy.optimize.least_squares",
        "solver_method": "trf",
        "solver_nfev": int(result.nfev),
        "solver_cost": float(result.cost),
        "solver_optimality": float(result.optimality),
        "solver_status": int(result.status),
        "solver_max_residual": float(np.max(np.abs(result.fun))),
        "final_reflux_ratio_R": float(op.reflux_flow_kgmol_per_s / max(op.distillate_flow_kgmol_per_s, 1e-15)),
        "skip_long_validation": bool(skip_long_validation),
    }

    state["convergence"] = {
        "passed": convergence_pass,
        "max_abs_dM_tray_dt": float(final_metrics.get("max_abs_dM_tray_dt", 0.0)) if final_metrics else 0.0,
        "max_abs_dnE_tray_dt": float(final_metrics.get("max_abs_dnE_tray_dt", 0.0)) if final_metrics else 0.0,
        "abs_dM_drum_dt": float(final_metrics.get("abs_dM_drum_dt", 0.0)) if final_metrics else 0.0,
        "abs_dM_sump_dt": float(final_metrics.get("abs_dM_sump_dt", 0.0)) if final_metrics else 0.0,
        "abs_dN_vapor_dt": float(final_metrics.get("abs_dN_vapor_dt", 0.0)) if final_metrics else 0.0,
        "abs_dP_top_dt": float(final_metrics.get("abs_dP_top_dt", 0.0)) if final_metrics else 0.0,
        "max_abs_dT_dt": float(final_metrics.get("max_abs_dT_dt", 0.0)) if final_metrics else 0.0,
        "mass_residual_rel": float(final_metrics.get("mass_residual_rel", 0.0)) if final_metrics else 0.0,
        "ethanol_residual_rel": float(final_metrics.get("ethanol_residual_rel", 0.0)) if final_metrics else 0.0,
        "energy_residual_rel": float(final_metrics.get("energy_residual_rel", 0.0)) if final_metrics else 0.0,
        "drum_level_pct": float(final_metrics.get("drum_level_pct", col.raw_reflux_drum_level_pct)) if final_metrics else float(col.raw_reflux_drum_level_pct),
        "sump_level_pct": float(final_metrics.get("sump_level_pct", col.raw_reboiler_level_pct)) if final_metrics else float(col.raw_reboiler_level_pct),
        "top_pressure_kpa": float(final_metrics.get("top_pressure_kpa", col._p_top_kpa)) if final_metrics else float(col._p_top_kpa),
        "top_ethanol_wt": float(final_metrics.get("top_ethanol_wt", col.top_ethanol_wt)) if final_metrics else float(col.top_ethanol_wt),
        "bottom_ethanol_wt": float(final_metrics.get("bottom_ethanol_wt", col.bottom_ethanol_wt)) if final_metrics else float(col.bottom_ethanol_wt),
        "ethanol_recovery_pct": float(final_metrics.get("ethanol_recovery_pct", 0.0)) if final_metrics else 0.0,
        "drift": drift,
        "drift_passed": bool(drift_pass),
        "mode_equivalence_passed": bool(eq_pass),
        "convergence_window_cycles": int(convergence_window_count),
        "generation_time_s": float(time.time() - t_start),
        "final_F_kgmol_per_s": float(op.feed_flow_kgmol_per_s),
        "final_D_kgmol_per_s": float(op.distillate_flow_kgmol_per_s),
        "final_B_kgmol_per_s": float(op.bottoms_flow_kgmol_per_s),
        "final_R_kgmol_per_s": float(op.reflux_flow_kgmol_per_s),
        "final_steam_kg_h": float(op.steam_flow_kg_h),
        "final_cooling_kg_h": float(op.cooling_flow_kg_h),
        "final_reflux_ratio": float(op.reflux_flow_kgmol_per_s / max(op.distillate_flow_kgmol_per_s, 1e-15)),
    }

    # 控制初始化表
    state["control_initialization"] = {
        **valve_cmds,
        "feed_flow_kg_h": float(col.feed_flow_kg_h),
        "reflux_flow_kg_h": float(col.reflux_flow_kg_h),
        "distillate_flow_kg_h": float(col.distillate_flow_kg_h),
        "bottoms_flow_kg_h": float(col.bottoms_flow_kg_h),
        "steam_flow_kg_h": float(col.steam_flow_kg_h),
        "cooling_flow_kg_h": float(col.cooling_flow_kg_h),
        "top_pressure_kpa": float(col.top_pressure_kpa),
        "drum_level_pct": float(col.raw_reflux_drum_level_pct),
        "sump_level_pct": float(col.raw_reboiler_level_pct),
        "top_ethanol_wt": float(col.top_ethanol_wt),
        "bottom_ethanol_wt": float(col.bottom_ethanol_wt),
        "sensitive_top_temperature_c": float(col.sensitive_top_temperature_c),
        "sensitive_bottom_temperature_c": float(col.sensitive_bottom_temperature_c),
    }

    # 标称 PV/SV/CSV/MV 表（todo/5.md §10.2）
    state["nominal_pid_values"] = {
        "feed_flow_pid": {
            "PV": float(col.feed_flow_kg_h), "SV": float(col.feed_flow_kg_h),
            "MV": float(valve_cmds["feed_valve_pct"]),
        },
        "pressure_pid": {
            "PV": float(col.top_pressure_kpa), "SV": 101.325,
            "MV": float(valve_cmds["cooling_valve_pct"]),
        },
        "reflux_drum_level_pid": {
            "PV": float(col.raw_reflux_drum_level_pct), "SV": 50.0,
            "MV": float(valve_cmds["distillate_valve_pct"]),
        },
        "reboiler_level_pid": {
            "PV": float(col.raw_reboiler_level_pct), "SV": 50.0,
            "MV": float(valve_cmds["bottoms_valve_pct"]),
        },
        "reflux_flow_pid": {
            "PV": float(col.reflux_flow_kg_h), "CSV": float(col.reflux_flow_kg_h),
            "MV": float(valve_cmds["reflux_valve_pct"]),
        },
        "steam_flow_pid": {
            "PV": float(col.steam_flow_kg_h), "CSV": float(col.steam_flow_kg_h),
            "MV": float(valve_cmds["steam_valve_pct"]),
        },
        "top_temp_pid": {
            "PV": float(col.sensitive_top_temperature_c),
            "SV": float(col.sensitive_top_temperature_c),
            "MV": float(col.reflux_flow_kg_h),
        },
        "bottom_temp_pid": {
            "PV": float(col.sensitive_bottom_temperature_c),
            "SV": float(col.sensitive_bottom_temperature_c),
            "MV": float(col.steam_flow_kg_h),
        },
        "top_quality_pid": {
            "PV": float(col.top_ethanol_wt), "SV": 0.85,
            "MV": float(col.reflux_flow_kg_h),
        },
        "bottom_quality_pid": {
            "PV": float(col.bottom_ethanol_wt), "SV": 0.015,
            "MV": float(col.steam_flow_kg_h),
        },
    }

    # 修复指令 §14：原子写入
    atomic_write_reference_state(output_path_obj, state)

    if verbose:
        print(f"  参考稳态已保存: {output_path}")
        print(f"  参数哈希: {state['params_hash']}")
        print(f"  收敛通过: {convergence_pass}")
        print(f"  R/D = {op.reflux_flow_kgmol_per_s/max(op.distillate_flow_kgmol_per_s,1e-15):.4f}")
        print()

    return state["convergence"]


# ====================================================================
# 主入口
# ====================================================================
def main() -> int:
    """生成参考稳态文件。"""
    output_path = str(
        _PROJECT_ROOT / "components" / "programs" / "data" / "ethanol_water_reference_state.json"
    )

    try:
        convergence = generate_reference_state(
            output_path=output_path,
            verbose=True,
            skip_long_validation=False,
        )
        if convergence["passed"]:
            print()
            print("✓ 参考稳态生成成功并通过验收")
            return 0
        else:
            print()
            print("✗ 参考稳态生成完成但未通过验收")
            print(f"  收敛详情: {convergence}")
            return 1
    except ReferenceStateGenerationError as e:
        print()
        print("✗ 参考稳态生成失败", file=sys.stderr)
        print(f"  失败门禁: {e}", file=sys.stderr)
        print(f"  是否修改正式文件: 否", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
