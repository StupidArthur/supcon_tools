"""
乙醇—水精馏塔执行机构和测量子系统。

包含：
1. ValveActuator：阀门动态（命令-实际开度一阶响应，线性/归一化等百分比特性）
2. ConcentrationAnalyzer：浓度分析仪（一阶滞后、采样间隔、传输延迟、噪声、零点漂移）

spec §6.2 阀门动态要求：
    - 模型内部为六个执行机构维护 command_pct, actual_pct, full_travel_time_s, characteristic
    - 每个阀门的实际开度、实际流量必须对外暴露
    - PID 的 MV 连接命令开度，PV 应连接实际测量流量

阶段 1 修正（todo/5.md §3、§4）：
    - ValveActuator 只负责 command_pct/actual_pct/flow_fraction/动态响应/阀门特性及反函数
    - 不再绑定具体物理单位（kg/h 或 kmol/s）；额定流量由调用方（精馏塔模型）持有
    - 等百分比特性改为归一化形式 f(x) = (R^x - 1) / (R - 1)，满足 f(0)=0、f(1)=1
    - 新增 get_flow_fraction() 和 opening_from_flow_fraction() API
    - 旧 get_flow_kgmol_per_s() 标记为 deprecated 兼容接口（仅在 max_flow_kgmol_per_s 显式
      传入时可用），正式模型不再使用

spec §6.3 测量动态要求：
    - 真实过程值和仪表值分开
    - 浓度分析仪至少支持：
        * 一阶测量滞后
        * 可配置采样间隔
        * 固定传输延迟
        * 可配置高斯噪声
        * 可配置零点漂移
        * 固定随机种子保证离线数据可复现
"""

from __future__ import annotations

import math
import warnings
from collections import deque
from typing import Literal, Optional

import numpy as np


# ====================================================================
# 阀门执行机构
# ====================================================================

class ValveActuator:
    """
    阀门执行机构（一阶响应 + 归一化流量特性）。

    职责（todo/5.md §3.1）：
        - command_pct / actual_pct 维护（一阶响应）
        - 阀门特性 f(x) 及反函数
        - 通过 get_flow_fraction() 返回归一化流量分数 ∈ [0, 1]
        - 通过 opening_from_flow_fraction() 由流量分数反算开度

    不负责：
        - 额定质量流量 kg/h 或摩尔流量 kmol/s（由调用方持有并换算）

    阀门动态：
        一阶响应 d(actual)/dt = (command - actual) / tau
        其中 tau = full_travel_time_s / 5（5τ 达到 99%）
        离散形式：actual_new = actual + (command - actual) * (1 - exp(-dt/tau))

    阀门特性（todo/5.md §4.1）：
        linear:             f(x) = x
        equal_percentage:   f(x) = (R^x - 1) / (R - 1)
        其中 x = actual_pct / 100 ∈ [0, 1]，R = rangeability。
        归一化等百分比满足 f(0)=0、f(1)=1，0% 开度下流量严格为零。

    反函数（用于根据目标流量反算开度）：
        linear:             x = ratio
        equal_percentage:   x = log(ratio * (R - 1) + 1) / log(R)
    """

    def __init__(
        self,
        name: str,
        full_travel_time_s: float,
        characteristic: Literal["linear", "equal_percentage"],
        initial_command_pct: float = 50.0,
        rangeability: float = 30.0,
        max_flow_kgmol_per_s: Optional[float] = None,
    ) -> None:
        if full_travel_time_s <= 0.0:
            raise ValueError(f"{name}: full_travel_time_s 必须>0，实际值={full_travel_time_s}")
        if characteristic not in ("linear", "equal_percentage"):
            raise ValueError(
                f"{name}: characteristic 必须为 'linear' 或 'equal_percentage'，"
                f"实际值={characteristic}"
            )
        if not (0.0 <= initial_command_pct <= 100.0):
            raise ValueError(
                f"{name}: initial_command_pct 必须位于 [0, 100]，实际值={initial_command_pct}"
            )
        if rangeability <= 1.0:
            raise ValueError(f"{name}: rangeability 必须>1，实际值={rangeability}")
        if max_flow_kgmol_per_s is not None and max_flow_kgmol_per_s <= 0.0:
            raise ValueError(
                f"{name}: max_flow_kgmol_per_s（兼容参数）必须>0，实际值={max_flow_kgmol_per_s}"
            )

        self.name = name
        self.full_travel_time_s = float(full_travel_time_s)
        self.characteristic = characteristic
        self.rangeability = float(rangeability)

        # 兼容字段：仅当显式传入时保留，供 deprecated get_flow_kgmol_per_s() 使用。
        # 正式模型不再依赖此字段，应使用 get_flow_fraction() + 调用方额定流量换算。
        self.max_flow_kgmol_per_s: Optional[float] = (
            float(max_flow_kgmol_per_s) if max_flow_kgmol_per_s is not None else None
        )

        # 一阶响应时间常数（5τ ≈ 满行程时间 → 99% 响应）
        self._tau_s = self.full_travel_time_s / 5.0

        # 开度状态（实际 = 命令初始值，避免启动时大幅运动）
        self.command_pct = float(initial_command_pct)
        self.actual_pct = float(initial_command_pct)

    # ------------------------------------------------------------------
    def set_command(self, command_pct: float) -> None:
        """设置命令开度（0~100%）。"""
        if not math.isfinite(command_pct):
            raise ValueError(f"{self.name}: command_pct 非有限: {command_pct}")
        self.command_pct = max(0.0, min(100.0, float(command_pct)))

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """一阶响应更新 actual_pct。"""
        if dt <= 0.0:
            return
        alpha = 1.0 - math.exp(-dt / self._tau_s)
        self.actual_pct = self.actual_pct + (self.command_pct - self.actual_pct) * alpha

    # ------------------------------------------------------------------
    def characteristic_function(self, x: float) -> float:
        """
        阀门特性函数 f(x) → [0, 1]。

        Args:
            x: 归一化开度 ∈ [0, 1]（actual_pct / 100）

        Returns:
            流量分数 ∈ [0, 1]。
            - linear: f(x) = x
            - equal_percentage: f(x) = (R^x - 1) / (R - 1)，满足 f(0)=0, f(1)=1
        """
        x = max(0.0, min(1.0, float(x)))
        if self.characteristic == "linear":
            return x
        # equal_percentage 归一化形式（todo/5.md §4.1）
        return (self.rangeability ** x - 1.0) / (self.rangeability - 1.0)

    # ------------------------------------------------------------------
    def inverse_characteristic_function(self, ratio: float) -> float:
        """
        阀门特性反函数 x = f⁻¹(ratio) → [0, 1]。

        Args:
            ratio: 流量分数 ∈ [0, 1]

        Returns:
            归一化开度 x ∈ [0, 1]。
            - linear: x = ratio
            - equal_percentage: x = log(ratio * (R - 1) + 1) / log(R)
        """
        ratio = max(0.0, min(1.0, float(ratio)))
        if self.characteristic == "linear":
            return ratio
        # equal_percentage 反函数
        return math.log(ratio * (self.rangeability - 1.0) + 1.0) / math.log(self.rangeability)

    # ------------------------------------------------------------------
    def get_flow_fraction(self) -> float:
        """
        返回当前 actual_pct 对应的归一化流量分数 ∈ [0, 1]。

        正式接口：调用方应使用此方法 + 自己持有的额定流量来计算物理流量。
        """
        x = self.actual_pct / 100.0
        return self.characteristic_function(x)

    # ------------------------------------------------------------------
    def opening_from_flow_fraction(self, ratio: float) -> float:
        """
        根据目标流量分数反算所需的 actual_pct（0~100%）。

        正式接口：用于稳态初始化时根据目标流量反算阀门初始开度。
        """
        x = self.inverse_characteristic_function(ratio)
        return x * 100.0

    # ------------------------------------------------------------------
    def get_flow_kgmol_per_s(self) -> float:
        """
        [DEPRECATED] 根据 actual_pct 和特性计算实际流量 (kmol/s)。

        仅为兼容旧测试保留。正式模型应使用 get_flow_fraction() + 调用方额定流量。
        此方法要求构造时显式传入 max_flow_kgmol_per_s，否则抛出 TypeError。
        """
        if self.max_flow_kgmol_per_s is None:
            raise TypeError(
                f"{self.name}: get_flow_kgmol_per_s() 已废弃，且未提供 max_flow_kgmol_per_s。"
                "请使用 get_flow_fraction() + 调用方额定流量换算。"
            )
        warnings.warn(
            f"{self.name}: get_flow_kgmol_per_s() 已废弃，请使用 get_flow_fraction()。",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.max_flow_kgmol_per_s * self.get_flow_fraction()

    # ------------------------------------------------------------------
    def to_state_dict(self) -> dict:
        """导出状态用于持久化。"""
        return {
            "command_pct": self.command_pct,
            "actual_pct": self.actual_pct,
        }

    # ------------------------------------------------------------------
    def load_state_dict(self, state: dict) -> None:
        """从 dict 恢复状态。"""
        self.command_pct = float(state["command_pct"])
        self.actual_pct = float(state["actual_pct"])


# ====================================================================
# 浓度分析仪
# ====================================================================

class ConcentrationAnalyzer:
    """
    浓度分析仪（一阶滞后 + 采样间隔 + 传输延迟 + 噪声 + 零点漂移）。

    spec §6.3 要求：
        - 一阶测量滞后（tau_lag）
        - 可配置采样间隔（sample_interval_s）
        - 固定传输延迟（transport_delay_s）
        - 可配置高斯噪声（noise_std）
        - 可配置零点漂移（drift_rate_per_s）
        - 固定随机种子（random_seed）

    模型：
        1. 真实值通过环形缓冲区保存历史（传输延迟）
        2. 延迟后的真实值进入一阶滞后：d(measured)/dt = (true - measured)/tau
        3. 采样点处叠加高斯噪声 + 零点漂移，得到最终输出
        4. 非采样点保持上一次输出（零阶保持）
    """

    def __init__(
        self,
        name: str,
        tau_lag_s: float = 30.0,
        sample_interval_s: float = 5.0,
        transport_delay_s: float = 60.0,
        noise_std: float = 0.0,
        drift_rate_per_s: float = 0.0,
        random_seed: int = 0,
        initial_true_value: float = 0.0,
        initial_measured_value: float = 0.0,
    ) -> None:
        if tau_lag_s <= 0.0:
            raise ValueError(f"{name}: tau_lag_s 必须>0，实际值={tau_lag_s}")
        if sample_interval_s <= 0.0:
            raise ValueError(f"{name}: sample_interval_s 必须>0，实际值={sample_interval_s}")
        if transport_delay_s < 0.0:
            raise ValueError(
                f"{name}: transport_delay_s 必须>=0，实际值={transport_delay_s}"
            )
        if noise_std < 0.0:
            raise ValueError(f"{name}: noise_std 必须>=0，实际值={noise_std}")

        self.name = name
        self.tau_lag_s = float(tau_lag_s)
        self.sample_interval_s = float(sample_interval_s)
        self.transport_delay_s = float(transport_delay_s)
        self.noise_std = float(noise_std)
        self.drift_rate_per_s = float(drift_rate_per_s)

        # 独立随机数生成器（保证可复现）
        self._rng = np.random.default_rng(random_seed)

        # 一阶滞后状态（连续值）
        self._lagged_value = float(initial_measured_value)

        # 当前对外输出（采样 + 噪声 + 漂移后的值）
        self.output = float(initial_measured_value)

        # 采样计时
        self._time_since_last_sample = 0.0
        self._total_time = 0.0

        # 传输延迟缓冲区（保存历史真实值）
        # 用 deque 保存 (timestamp, true_value)
        self._delay_buffer: deque = deque()
        self._delay_buffer.append((0.0, float(initial_true_value)))

    # ------------------------------------------------------------------
    def update(self, true_value: float, dt: float) -> float:
        """
        一个周期更新。

        Args:
            true_value: 当前周期的真实过程值
            dt: 周期长度 (s)

        Returns:
            当前周期的分析仪输出（含噪声、漂移、采样保持）
        """
        if dt <= 0.0:
            return self.output

        self._total_time += dt

        # 1. 把当前真实值加入延迟缓冲区
        self._delay_buffer.append((self._total_time, float(true_value)))

        # 2. 清理过期数据（保留至少 transport_delay_s 之前的数据）
        cutoff = self._total_time - self.transport_delay_s
        while len(self._delay_buffer) > 1 and self._delay_buffer[0][0] < cutoff:
            # 保留最后一个早于 cutoff 的点，用于插值
            if self._delay_buffer[1][0] <= cutoff:
                self._delay_buffer.popleft()
            else:
                break

        # 3. 获取延迟后的真实值（线性插值）
        if len(self._delay_buffer) >= 2:
            t0, v0 = self._delay_buffer[0]
            t1, v1 = self._delay_buffer[1]
            if t1 > t0:
                # cutoff 在 [t0, t1] 区间
                alpha = (cutoff - t0) / (t1 - t0)
                alpha = max(0.0, min(1.0, alpha))
                delayed_true = v0 + alpha * (v1 - v0)
            else:
                delayed_true = v1
        else:
            delayed_true = self._delay_buffer[0][1]

        # 4. 一阶滞后更新：d(lagged)/dt = (delayed_true - lagged) / tau
        alpha = 1.0 - math.exp(-dt / self.tau_lag_s)
        self._lagged_value = self._lagged_value + (delayed_true - self._lagged_value) * alpha

        # 5. 采样判断：是否到达采样时刻
        self._time_since_last_sample += dt
        if self._time_since_last_sample >= self.sample_interval_s:
            # 采样点：叠加噪声 + 零点漂移
            noise = 0.0
            if self.noise_std > 0.0:
                noise = float(self._rng.normal(0.0, self.noise_std))
            drift = self.drift_rate_per_s * self._total_time
            self.output = self._lagged_value + noise + drift
            # 物理范围限制（质量分数 0~1）
            self.output = max(0.0, min(1.0, self.output))
            # 重置采样计时（保留余数以保持采样相位）
            self._time_since_last_sample -= self.sample_interval_s
            # 防止累积
            if self._time_since_last_sample > self.sample_interval_s:
                self._time_since_last_sample = 0.0

        # 非采样点：保持上一次输出（零阶保持）
        return self.output

    # ------------------------------------------------------------------
    def reset(self, true_value: float) -> None:
        """重置分析仪到指定真实值（用于初始化或重新加载状态）。"""
        self._lagged_value = float(true_value)
        self.output = float(true_value)
        self._time_since_last_sample = 0.0
        self._total_time = 0.0
        self._delay_buffer.clear()
        self._delay_buffer.append((0.0, float(true_value)))

    # ------------------------------------------------------------------
    def to_state_dict(self) -> dict:
        """导出状态用于持久化。"""
        return {
            "lagged_value": self._lagged_value,
            "output": self.output,
            "time_since_last_sample": self._time_since_last_sample,
            "total_time": self._total_time,
            "delay_buffer": list(self._delay_buffer),
            # RNG 状态：保存以恢复随机数序列
            "rng_state": self._rng.bit_generator.state,
        }

    # ------------------------------------------------------------------
    def load_state_dict(self, state: dict) -> None:
        """从 dict 恢复状态。"""
        self._lagged_value = float(state["lagged_value"])
        self.output = float(state["output"])
        self._time_since_last_sample = float(state["time_since_last_sample"])
        self._total_time = float(state["total_time"])
        self._delay_buffer = deque(
            (float(t), float(v)) for t, v in state["delay_buffer"]
        )
        self._rng.bit_generator.state = state["rng_state"]
