"""
乙醇—水精馏塔参考稳态生成器（todo/5.md §9.3）。

使用伪时间松弛和临时调节器（仅存在于本工具，不进入正式模型）收敛到稳态，
然后将状态保存为 components/programs/data/ethanol_water_reference_state.json。

策略（4 回路 PI + 固定 V）：
    固定进料 F 和过程蒸气量 V，使用 4 个 PI 调节器：
    1. 塔顶压力 → 冷却水流量（正作用）
    2. 回流罐液位 → D 塔顶采出（正作用）
    3. 塔釜液位 → B 塔底采出（正作用）
    4. 塔顶乙醇浓度 xD → R 回流量（反作用：xD 高 → R 低）

    V 固定不与 R+D 代数耦合，避免正反馈循环：
    之前 V = R + D 时，R 降 → V 降 → V_condense 降 → D 降 → V 降 …
    固定 V 后，液位控制器动态调整 D，稳态自然满足 V = R + D (CMO)。

    12 块理论板 + 当前 VLE 的分离能力超过设计目标（R=3.0 时 xD=0.889）。
    通过 xD→R 控制器自动找到使 xD≈0.85 的 R*，xB 由塔分离特性决定。

收敛准则（todo/5.md §9.4）：连续 1800 s 同时满足收敛阈值。

使用方法：
    python tools/generate_ethanol_water_reference_state.py

输出：
    components/programs/data/ethanol_water_reference_state.json
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import components.programs  # noqa: F401 触发组件注册
from components.programs.ethanol_water_distillation import ETHANOL_WATER_DISTILLATION
from components.thermo.ethanol_water import (
    MW_ETHANOL_KG_PER_KMOL,
    MW_WATER_KG_PER_KMOL,
    heat_of_vaporization_kj_per_kmol,
)


# ====================================================================
# 默认参考工况参数（todo/5.md §2.3）
# ====================================================================
REFERENCE_PARAMS: Dict[str, Any] = {
    "cycle_time": 0.5,
    "max_internal_step": 0.25,
    "initialization_mode": "WARM_GUESS",
    "random_seed": 20260719,
    # 标称流量初值（kmol/s）—— 物料衡算闭合：F = D + B
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

# 冷却水流量初始猜测（kg/h）
INITIAL_COOLING_FLOW_KG_H = 3600.0

# 固定进料
FIXED_FEED_FLOW_KGMOL_PER_S = 0.00130716777

# 固定过程蒸气量 V（kmol/s）—— 不与 R+D 代数耦合，避免正反馈
# 设计点 V = 4*D = 0.000837；控制器会调整 R 使 xD≈0.85
FIXED_VAPOR_BOILUP_KGMOL_PER_S = 0.00083734082


# ====================================================================
# 临时 PI 调节器（仅本工具使用，不进入正式模型）
# ====================================================================
class PIController:
    """
    通用 PI 调节器，支持正/反作用。

    output = bias + Kp * err + Ki * integral
    其中 err = PV - SP（正作用：PV 高 → output 高）
    或 err = SP - PV（反作用：PV 高 → output 低）

    抗饱和：仅当输出在范围内时才积分。
    """

    def __init__(
        self,
        bias: float,
        kp: float,
        ki: float,
        output_min: float,
        output_max: float,
        reverse_acting: bool = False,
    ) -> None:
        self.bias = float(bias)
        self.kp = float(kp)
        self.ki = float(ki)
        self.output_min = float(output_min)
        self.output_max = float(output_max)
        self.reverse_acting = bool(reverse_acting)
        self.integral = 0.0
        self.output = float(bias)

    def update(self, pv: float, sp: float, dt: float) -> float:
        if self.reverse_acting:
            err = float(sp) - float(pv)
        else:
            err = float(pv) - float(sp)
        if self.output_min < self.output < self.output_max:
            self.integral += err * dt
        self.output = self.bias + self.kp * err + self.ki * self.integral
        self.output = max(self.output_min, min(self.output_max, self.output))
        return self.output

    def reset(self, bias: float) -> None:
        self.bias = float(bias)
        self.integral = 0.0
        self.output = float(bias)


# ====================================================================
# 基础控制器：压力 + 液位 + 组成（V 固定，不与 R+D 耦合）
# ====================================================================
class BasicController:
    """
    4 回路 PI 控制器，V 固定不耦合。

    回路：
    1. 压力 → 冷却水 (kg/h)，正作用
    2. 回流罐液位 (%) → D (kmol/s)，正作用
    3. 塔釜液位 (%) → B (kmol/s)，正作用
    4. xD → R (kmol/s)，反作用（xD 高 → R 低）

    V 固定为 FIXED_VAPOR_BOILUP_KGMOL_PER_S，由液位控制器动态调整 D
    使稳态自然满足 V = R + D (CMO)。
    """

    def __init__(self) -> None:
        # 压力 → 冷却水 (kg/h)，正作用（PV-SP）
        self.pressure = PIController(
            bias=INITIAL_COOLING_FLOW_KG_H,
            kp=80.0, ki=8.0,
            output_min=200.0, output_max=12000.0,
            reverse_acting=False,
        )
        # 回流罐液位 (%) → D (kmol/s)，正作用（PV-SP）
        # 液位高 → D 大（多采出）
        self.drum_level = PIController(
            bias=0.00020933521,
            kp=5.0e-6, ki=2.0e-6,
            output_min=1e-6, output_max=0.0015,
            reverse_acting=False,
        )
        # 塔釜液位 (%) → B (kmol/s)，正作用（PV-SP）
        # 液位高 → B 大（多采出）
        self.sump_level = PIController(
            bias=0.00109783256,
            kp=5.0e-5, ki=2.0e-5,
            output_min=1e-6, output_max=0.005,
            reverse_acting=False,
        )
        # xD → R (kmol/s)，反作用（xD 高 → R 低）
        # 增益较慢，避免在初始平衡阶段过反应
        # R_max = 0.75*V，确保 D = V - R ≥ 0.25*V > 0
        self.top_quality = PIController(
            bias=0.00062800562,  # R = 3.0 * D 初猜
            kp=3.0e-5, ki=2.0e-6,
            output_min=1e-5, output_max=0.000628,  # R_max = 0.75*V
            reverse_acting=True,
        )

    def reset(self) -> None:
        self.pressure.reset(INITIAL_COOLING_FLOW_KG_H)
        self.drum_level.reset(0.00020933521)
        self.sump_level.reset(0.00109783256)
        self.top_quality.reset(0.00062800562)


# ====================================================================
# 收敛检查
# ====================================================================
def compute_convergence_metrics(col: ETHANOL_WATER_DISTILLATION) -> Dict[str, float]:
    """计算本期收敛指标（todo/5.md §9.4）。"""
    metrics = {
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
    return metrics


def check_convergence(metrics: Dict[str, float]) -> bool:
    """检查是否满足 todo/5.md §9.4 收敛阈值。"""
    if not (47.0 <= metrics["drum_level_pct"] <= 53.0):
        return False
    if not (47.0 <= metrics["sump_level_pct"] <= 53.0):
        return False
    if abs(metrics["top_pressure_kpa"] - 101.325) > 0.10:
        return False
    if not (0.82 <= metrics["top_ethanol_wt"] <= 0.88):
        return False
    if not (0.010 <= metrics["bottom_ethanol_wt"] <= 0.020):
        return False
    if metrics["ethanol_recovery_pct"] < 95.0:
        return False
    if metrics["mass_residual_rel"] > 0.001:
        return False
    if metrics["ethanol_residual_rel"] > 0.002:
        return False
    if metrics["energy_residual_rel"] > 0.01:
        return False
    return True


def check_coarse_convergence(metrics: Dict[str, float]) -> bool:
    """宽松收敛：仅检查组成是否在目标附近。"""
    return (
        0.83 <= metrics["top_ethanol_wt"] <= 0.87
        and 0.008 <= metrics["bottom_ethanol_wt"] <= 0.025
        and 40.0 <= metrics["drum_level_pct"] <= 60.0
        and 40.0 <= metrics["sump_level_pct"] <= 60.0
        and abs(metrics["top_pressure_kpa"] - 101.325) < 0.5
    )


# ====================================================================
# 阀位反算
# ====================================================================
def compute_valve_pct_from_flow(
    col: ETHANOL_WATER_DISTILLATION,
    feed_flow_kgmol_per_s: float,
    reflux_flow_kgmol_per_s: float,
    distillate_flow_kgmol_per_s: float,
    bottoms_flow_kgmol_per_s: float,
    steam_flow_kg_h: float,
    cooling_flow_kg_h: float,
) -> Dict[str, float]:
    """根据目标质量流量反算各阀位命令。"""
    xD = col._nE_drum / max(col._M_drum, 1e-15)
    xD = max(0.0, min(1.0, xD))
    xB = col._nE_sump / max(col._M_sump, 1e-15)
    xB = max(0.0, min(1.0, xB))
    mw_drum = xD * MW_ETHANOL_KG_PER_KMOL + (1.0 - xD) * MW_WATER_KG_PER_KMOL
    mw_sump = xB * MW_ETHANOL_KG_PER_KMOL + (1.0 - xB) * MW_WATER_KG_PER_KMOL
    xF = col._feed_ethanol_wt
    xF_mol = (xF / MW_ETHANOL_KG_PER_KMOL) / (
        xF / MW_ETHANOL_KG_PER_KMOL + (1.0 - xF) / MW_WATER_KG_PER_KMOL
    )
    mw_feed = xF_mol * MW_ETHANOL_KG_PER_KMOL + (1.0 - xF_mol) * MW_WATER_KG_PER_KMOL

    feed_mass_kg_h = feed_flow_kgmol_per_s * mw_feed * 3600.0
    reflux_mass_kg_h = reflux_flow_kgmol_per_s * mw_drum * 3600.0
    distillate_mass_kg_h = distillate_flow_kgmol_per_s * mw_drum * 3600.0
    bottoms_mass_kg_h = bottoms_flow_kgmol_per_s * mw_sump * 3600.0

    max_flows = col._valve_max_flow_kg_per_h

    def _pct(flow_kg_h: float, max_kg_h: float, valve_name: str) -> float:
        if max_kg_h <= 0:
            return 0.0
        ratio = max(0.0, min(1.0, flow_kg_h / max_kg_h))
        valve = col._valves[valve_name]
        return valve.opening_from_flow_fraction(ratio)

    return {
        "feed_valve_pct": _pct(feed_mass_kg_h, max_flows["feed"], "feed"),
        "reflux_valve_pct": _pct(reflux_mass_kg_h, max_flows["reflux"], "reflux"),
        "distillate_valve_pct": _pct(distillate_mass_kg_h, max_flows["distillate"], "distillate"),
        "bottoms_valve_pct": _pct(bottoms_mass_kg_h, max_flows["bottoms"], "bottoms"),
        "steam_valve_pct": _pct(steam_flow_kg_h, max_flows["steam"], "steam"),
        "cooling_valve_pct": _pct(cooling_flow_kg_h, max_flows["cooling"], "cooling"),
    }


def compute_steam_flow_from_v(
    col: ETHANOL_WATER_DISTILLATION, V_flow: float
) -> float:
    """由过程蒸气量 V_boil (kmol/s) 反推公用工程蒸汽流量 (kg/h)。"""
    xB = col._nE_sump / max(col._M_sump, 1e-15)
    xB = max(0.0, min(1.0, xB))
    dh_vap_sump = max(heat_of_vaporization_kj_per_kmol(xB), 1.0)
    return (
        V_flow * dh_vap_sump * 3600.0
        / (float(col.steam_latent_heat_kj_per_kg) * float(col.steam_heat_transfer_efficiency))
    )


def _sync_valves_for_vapor_bypass(
    col: ETHANOL_WATER_DISTILLATION,
    V_flow: float,
    cooling_flow_kg_h: float,
) -> Tuple[float, float]:
    """
    在直接流量模式（vapor_boilup bypass）下，同步阀门 actual_pct 以便后续阀位反算。
    返回 (steam_flow_kg_h, cooling_pct)。
    """
    # 冷却水阀
    cooling_ratio = cooling_flow_kg_h / col._valve_max_flow_kg_per_h["cooling"]
    cooling_ratio = max(0.0, min(1.0, cooling_ratio))
    cooling_pct = col._valves["cooling"].opening_from_flow_fraction(cooling_ratio)
    col._valves["cooling"].command_pct = cooling_pct
    col._valves["cooling"].actual_pct = cooling_pct

    # 蒸汽阀（由 V_flow 反推）
    steam_flow_kg_h = compute_steam_flow_from_v(col, V_flow)
    col._last_steam_flow_kg_per_h = steam_flow_kg_h
    steam_ratio = steam_flow_kg_h / col._valve_max_flow_kg_per_h["steam"]
    steam_ratio = max(0.0, min(1.0, steam_ratio))
    steam_pct = col._valves["steam"].opening_from_flow_fraction(steam_ratio)
    col._valves["steam"].command_pct = steam_pct
    col._valves["steam"].actual_pct = steam_pct

    col._last_cooling_flow_kg_per_h = cooling_flow_kg_h
    return steam_flow_kg_h, cooling_pct


def _run_settling_phase(
    col: ETHANOL_WATER_DISTILLATION,
    controller: BasicController,
    n_cycles: int,
    cycle_time: float,
    verbose: bool = False,
    label: str = "",
) -> Dict[str, float]:
    """
    使用 4 回路 PI + 固定 V 跑 n_cycles 周期让系统松弛。
    V 固定为 FIXED_VAPOR_BOILUP_KGMOL_PER_S，不与 R+D 耦合。
    返回最后周期的收敛指标。
    """
    metrics: Dict[str, float] = {}
    V_flow = FIXED_VAPOR_BOILUP_KGMOL_PER_S
    for cycle in range(n_cycles):
        # PI 调节器
        cooling_flow_kg_h = controller.pressure.update(
            float(col.top_pressure_kpa), TARGET_TOP_PRESSURE_KPA, cycle_time
        )
        D_flow = controller.drum_level.update(
            float(col.raw_reflux_drum_level_pct), TARGET_DRUM_LEVEL_PCT, cycle_time
        )
        B_flow = controller.sump_level.update(
            float(col.raw_reboiler_level_pct), TARGET_SUMP_LEVEL_PCT, cycle_time
        )
        R_flow = controller.top_quality.update(
            float(col.top_ethanol_wt), TARGET_TOP_ETHANOL_WT, cycle_time
        )
        # V 固定，不与 R+D 耦合

        _sync_valves_for_vapor_bypass(col, V_flow, cooling_flow_kg_h)

        col.execute(
            feed_flow_kgmol_per_s=FIXED_FEED_FLOW_KGMOL_PER_S,
            reflux_flow_kgmol_per_s=R_flow,
            distillate_flow_kgmol_per_s=D_flow,
            bottoms_flow_kgmol_per_s=B_flow,
            vapor_boilup_kgmol_per_s=V_flow,
        )

        metrics = compute_convergence_metrics(col)

        if verbose and (cycle % 500 == 0 or cycle == n_cycles - 1):
            print(
                f"  [{label}] cycle {cycle:5d} | "
                f"P={metrics['top_pressure_kpa']:7.3f} | "
                f"drum={metrics['drum_level_pct']:5.1f}% sump={metrics['sump_level_pct']:5.1f}% | "
                f"xD={metrics['top_ethanol_wt']:.4f} xB={metrics['bottom_ethanol_wt']:.4f} | "
                f"R={R_flow:.5e} V={V_flow:.5e} | "
                f"D={D_flow:.5e} B={B_flow:.5e} | "
                f"cw={cooling_flow_kg_h:6.0f}"
            )
    return metrics


# ====================================================================
# 主生成流程
# ====================================================================
def generate_reference_state(
    output_path: str,
    verbose: bool = True,
) -> Dict[str, Any]:
    """生成参考稳态。"""
    if verbose:
        print("=" * 70)
        print("乙醇—水精馏塔参考稳态生成器（todo/5.md §9.3）")
        print("=" * 70)
        print()
        print("策略：4 回路 PI + 固定 V")
        print("  压力 → 冷却水（正作用）")
        print("  回流罐液位 → D（正作用）")
        print("  塔釜液位 → B（正作用）")
        print("  xD → R（反作用）")
        print("  V 固定，不与 R+D 耦合，避免正反馈循环")
        print(f"  R_max = 0.75*V = {0.75*FIXED_VAPOR_BOILUP_KGMOL_PER_S:.6e} (确保 D > 0)")
        print()

    # 构造模型（WARM_GUESS 初猜）
    col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
    cycle_time = float(REFERENCE_PARAMS["cycle_time"])
    controller = BasicController()

    t_start = time.time()

    # ==================================================================
    # 阶段 1：松弛稳定（8000 周期 = 4000 s）
    # ==================================================================
    if verbose:
        print("阶段 1：松弛稳定 8000 周期（4000 s）")
        print("-" * 70)
        print(f"  F={FIXED_FEED_FLOW_KGMOL_PER_S:.8f} kmol/s (固定)")
        print(f"  目标: P=101.325 kPa, drum=50%, sump=50%, xD=0.85, xB≈0.015")
        print()

    metrics = _run_settling_phase(
        col, controller,
        n_cycles=8000, cycle_time=cycle_time,
        verbose=verbose, label="relax",
    )

    t_phase1 = time.time() - t_start
    if verbose:
        print(f"\n阶段 1 完成: xD={metrics['top_ethanol_wt']:.4f}, xB={metrics['bottom_ethanol_wt']:.4f}")
        print(f"  drum={metrics['drum_level_pct']:.1f}%, sump={metrics['sump_level_pct']:.1f}%, P={metrics['top_pressure_kpa']:.3f}")
        print(f"  阶段 1 耗时: {t_phase1:.1f} s")
        print()

    # ==================================================================
    # 阶段 2：收敛窗口验证（3600 周期 = 1800 s）
    # ==================================================================
    if verbose:
        print("阶段 2：收敛窗口验证 3600 周期（1800 s）")
        print("-" * 70)

    convergence_window = 3600  # 1800 s @ 0.5 s
    window_count = 0
    final_metrics: Dict[str, float] = {}
    V_flow = FIXED_VAPOR_BOILUP_KGMOL_PER_S

    for cycle in range(convergence_window):
        cooling_flow_kg_h = controller.pressure.update(
            float(col.top_pressure_kpa), TARGET_TOP_PRESSURE_KPA, cycle_time
        )
        D_flow = controller.drum_level.update(
            float(col.raw_reflux_drum_level_pct), TARGET_DRUM_LEVEL_PCT, cycle_time
        )
        B_flow = controller.sump_level.update(
            float(col.raw_reboiler_level_pct), TARGET_SUMP_LEVEL_PCT, cycle_time
        )
        R_flow = controller.top_quality.update(
            float(col.top_ethanol_wt), TARGET_TOP_ETHANOL_WT, cycle_time
        )

        _sync_valves_for_vapor_bypass(col, V_flow, cooling_flow_kg_h)

        col.execute(
            feed_flow_kgmol_per_s=FIXED_FEED_FLOW_KGMOL_PER_S,
            reflux_flow_kgmol_per_s=R_flow,
            distillate_flow_kgmol_per_s=D_flow,
            bottoms_flow_kgmol_per_s=B_flow,
            vapor_boilup_kgmol_per_s=V_flow,
        )

        final_metrics = compute_convergence_metrics(col)

        if check_convergence(final_metrics):
            window_count += 1
        else:
            window_count = 0

        if verbose and (cycle % 500 == 0 or cycle == convergence_window - 1):
            print(
                f"  cycle {cycle:5d} | "
                f"P={final_metrics['top_pressure_kpa']:7.3f} | "
                f"drum={final_metrics['drum_level_pct']:5.1f}% sump={final_metrics['sump_level_pct']:5.1f}% | "
                f"xD={final_metrics['top_ethanol_wt']:.4f} xB={final_metrics['bottom_ethanol_wt']:.4f} | "
                f"rec={final_metrics['ethanol_recovery_pct']:5.1f}% | "
                f"mRes={final_metrics['mass_residual_rel']:.2e} | "
                f"win={window_count}/{convergence_window}"
            )

    if verbose:
        print(f"\n阶段 2 完成: 收敛窗口 {window_count}/{convergence_window}")
        print()

    # 记录直接流量模式的最终流量
    final_F = FIXED_FEED_FLOW_KGMOL_PER_S
    final_D = float(col._last_distillate_flow)
    final_B = float(col._last_bottoms_flow)
    final_R = float(col._last_reflux_flow)
    final_V = float(col._last_vapor_boilup)
    final_cooling_kg_h = float(col._last_cooling_flow_kg_per_h)
    final_steam_kg_h = float(col._last_steam_flow_kg_per_h)

    if verbose:
        print(f"  直接流量模式最终值:")
        print(f"    F={final_F:.6e}, D={final_D:.6e}, B={final_B:.6e} kmol/s")
        print(f"    R={final_R:.6e} (R/D={final_R/max(final_D,1e-15):.3f}), V={final_V:.6e}")
        print(f"    steam={final_steam_kg_h:.2f} kg/h, cooling={final_cooling_kg_h:.2f} kg/h")
        print()

    # ==================================================================
    # 阶段 3：阀位切换 + 3600 s 漂移验证
    # ==================================================================
    if verbose:
        print("阶段 3：切换到阀位模式 + 3600 s 漂移验证")
        print("-" * 70)

    # 反算阀位
    valve_cmds = compute_valve_pct_from_flow(
        col,
        feed_flow_kgmol_per_s=final_F,
        reflux_flow_kgmol_per_s=final_R,
        distillate_flow_kgmol_per_s=final_D,
        bottoms_flow_kgmol_per_s=final_B,
        steam_flow_kg_h=final_steam_kg_h,
        cooling_flow_kg_h=final_cooling_kg_h,
    )

    if verbose:
        print(f"  反算阀位: {valve_cmds}")

    # 设置阀门 actual_pct = command_pct（无扰切换）
    for key, pct in valve_cmds.items():
        valve_name = key.replace("_valve_pct", "")
        col._valves[valve_name].command_pct = pct
        col._valves[valve_name].actual_pct = pct

    # 阀位模式跑 1000 周期稳定
    if verbose:
        print("\n  阀位模式稳定 1000 周期:")
    for cycle in range(1000):
        col.execute(**valve_cmds)
        if verbose and (cycle % 200 == 0 or cycle == 999):
            m = compute_convergence_metrics(col)
            print(
                f"  cycle {cycle:5d} | "
                f"P={m['top_pressure_kpa']:7.3f} | "
                f"drum={m['drum_level_pct']:5.1f}% sump={m['sump_level_pct']:5.1f}% | "
                f"xD={m['top_ethanol_wt']:.4f} xB={m['bottom_ethanol_wt']:.4f}"
            )

    metrics_after_switch = compute_convergence_metrics(col)
    if verbose:
        print(
            f"\n  稳定后: P={metrics_after_switch['top_pressure_kpa']:7.3f} | "
            f"drum={metrics_after_switch['drum_level_pct']:5.1f}% "
            f"sump={metrics_after_switch['sump_level_pct']:5.1f}% | "
            f"xD={metrics_after_switch['top_ethanol_wt']:.4f} "
            f"xB={metrics_after_switch['bottom_ethanol_wt']:.4f}"
        )

    # 记录初始状态（用于漂移计算）
    p_init = float(col.top_pressure_kpa)
    drum_init = float(col.raw_reflux_drum_level_pct)
    sump_init = float(col.raw_reboiler_level_pct)
    t_top_init = float(col.top_temperature_c)
    t_bot_init = float(col.bottom_temperature_c)
    xD_init = float(col.top_ethanol_wt)
    xB_init = float(col.bottom_ethanol_wt)

    # 跑 7200 周期（3600 s）验证漂移
    if verbose:
        print(f"\n  3600 s 漂移验证（7200 周期）:")
    for cycle in range(7200):
        col.execute(**valve_cmds)
        if verbose and cycle % 1000 == 0:
            m = compute_convergence_metrics(col)
            print(
                f"  cycle {cycle:5d} | "
                f"P={m['top_pressure_kpa']:7.3f} | "
                f"drum={m['drum_level_pct']:5.1f}% sump={m['sump_level_pct']:5.1f}% | "
                f"xD={m['top_ethanol_wt']:.4f} xB={m['bottom_ethanol_wt']:.4f}"
            )

    # 记录最终状态
    p_final = float(col.top_pressure_kpa)
    drum_final = float(col.raw_reflux_drum_level_pct)
    sump_final = float(col.raw_reboiler_level_pct)
    t_top_final = float(col.top_temperature_c)
    t_bot_final = float(col.bottom_temperature_c)
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

    t_total = time.time() - t_start

    # ==================================================================
    # 保存参考状态
    # ==================================================================
    state = col._get_full_state_dict()

    final_metrics = compute_convergence_metrics(col)
    convergence_pass = bool(drift_pass and check_convergence(final_metrics))

    state["metadata"] = {
        "model_name": "ETHANOL_WATER_DISTILLATION",
        "description": "Ethanol-water distillation reference steady state (auto-generated)",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generation_tool": "tools/generate_ethanol_water_reference_state.py",
        "generation_cycle_time_s": REFERENCE_PARAMS["cycle_time"],
        "generation_internal_step_s": REFERENCE_PARAMS["max_internal_step"],
        "thermo_version": "antoine_nrtl_arce_srnl_v1",
        "generation_method": "4_loop_pi_with_fixed_vapor_boilup",
        "final_reflux_ratio_R": float(final_R / max(final_D, 1e-15)),
    }

    state["convergence"] = {
        "passed": convergence_pass,
        "mass_residual_rel": float(final_metrics["mass_residual_rel"]),
        "ethanol_residual_rel": float(final_metrics["ethanol_residual_rel"]),
        "energy_residual_rel": float(final_metrics["energy_residual_rel"]),
        "drum_level_pct": float(final_metrics["drum_level_pct"]),
        "sump_level_pct": float(final_metrics["sump_level_pct"]),
        "top_pressure_kpa": float(final_metrics["top_pressure_kpa"]),
        "top_ethanol_wt": float(final_metrics["top_ethanol_wt"]),
        "bottom_ethanol_wt": float(final_metrics["bottom_ethanol_wt"]),
        "ethanol_recovery_pct": float(final_metrics["ethanol_recovery_pct"]),
        "drift": drift,
        "drift_passed": bool(drift_pass),
        "convergence_window_cycles": int(window_count),
        "generation_time_s": float(t_total),
        "final_F_kgmol_per_s": float(final_F),
        "final_D_kgmol_per_s": float(final_D),
        "final_B_kgmol_per_s": float(final_B),
        "final_R_kgmol_per_s": float(final_R),
        "final_V_kgmol_per_s": float(final_V),
        "final_reflux_ratio": float(final_R / max(final_D, 1e-15)),
    }

    # 控制初始化表
    state["control_initialization"] = {
        "feed_valve_pct": float(valve_cmds["feed_valve_pct"]),
        "reflux_valve_pct": float(valve_cmds["reflux_valve_pct"]),
        "distillate_valve_pct": float(valve_cmds["distillate_valve_pct"]),
        "bottoms_valve_pct": float(valve_cmds["bottoms_valve_pct"]),
        "steam_valve_pct": float(valve_cmds["steam_valve_pct"]),
        "cooling_valve_pct": float(valve_cmds["cooling_valve_pct"]),
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
            "PV": float(col.feed_flow_kg_h),
            "SV": float(col.feed_flow_kg_h),
            "MV": float(valve_cmds["feed_valve_pct"]),
        },
        "pressure_pid": {
            "PV": float(col.top_pressure_kpa),
            "SV": 101.325,
            "MV": float(valve_cmds["cooling_valve_pct"]),
        },
        "reflux_drum_level_pid": {
            "PV": float(col.raw_reflux_drum_level_pct),
            "SV": 50.0,
            "MV": float(valve_cmds["distillate_valve_pct"]),
        },
        "reboiler_level_pid": {
            "PV": float(col.raw_reboiler_level_pct),
            "SV": 50.0,
            "MV": float(valve_cmds["bottoms_valve_pct"]),
        },
        "reflux_flow_pid": {
            "PV": float(col.reflux_flow_kg_h),
            "CSV": float(col.reflux_flow_kg_h),
            "MV": float(valve_cmds["reflux_valve_pct"]),
        },
        "steam_flow_pid": {
            "PV": float(col.steam_flow_kg_h),
            "CSV": float(col.steam_flow_kg_h),
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
            "PV": float(col.top_ethanol_wt),
            "SV": 0.85,
            "MV": float(col.reflux_flow_kg_h),
        },
        "bottom_quality_pid": {
            "PV": float(col.bottom_ethanol_wt),
            "SV": 0.015,
            "MV": float(col.steam_flow_kg_h),
        },
    }

    # 保存
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"参考稳态已保存: {output_path}")
        print(f"参数哈希: {state['params_hash']}")
        print(f"收敛通过: {convergence_pass}")
        print(f"R/D = {final_R/max(final_D,1e-15):.4f}")
        print()
        print("标称控制初值表：")
        print("-" * 70)
        for pid_name, vals in state["nominal_pid_values"].items():
            print(f"  {pid_name:25s}: {vals}")
        print("-" * 70)

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
        convergence = generate_reference_state(output_path=output_path, verbose=True)
        if convergence["passed"]:
            print()
            print("✓ 参考稳态生成成功并通过验收")
            return 0
        else:
            print()
            print("✗ 参考稳态生成完成但未通过验收")
            print(f"  收敛详情: {convergence}")
            return 1
    except RuntimeError as e:
        print(f"✗ 生成失败: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
