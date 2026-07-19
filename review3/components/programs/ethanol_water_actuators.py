"""
乙醇—水精馏塔执行机构和测量子系统（阶段 D）。

包含：
1. ValveActuator：阀门动态（命令-实际开度一阶响应，线性/等百分比特性）
2. ConcentrationAnalyzer：浓度分析仪（一阶滞后、采样间隔、传输延迟、噪声、零点漂移）

spec §6.2 阀门动态要求：
    - 模型内部为六个执行机构维护 command_pct, actual_pct, full_travel_time_s, characteristic
    - 每个阀门的实际开度、实际流量必须对外暴露
    - PID 的 MV 连接命令开度，PV 应连接实际测量流量

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
from collections import deque
from typing import Literal

import numpy as np


# ====================================================================
# 阀门执行机构
# ====================================================================

class ValveActuator:
    """
    阀门执行机构（一阶响应 + 流量特性）。

    属性：
        name: 阀门名称
        command_pct: 命令开度（0~100%）
        actual_pct: 实际开度（0~100%），滞后于 command
        full_travel_time_s: 满行程时间（0→100% 或 100→0%）
        characteristic: 特性 'linear' 或 'equal_percentage'
        max_flow_kgmol_per_s: 100% 开度下的最大流量 (kmol/s)
        rangeability: 等百分比阀的可调比（典型值 30）

    阀门动态：
        一阶响应 d(actual)/dt = (command - actual) / tau
        其中 tau = full_travel_time_s / 5（5τ 达到 99%）
        离散形式：actual_new = actual + (command - actual) * (1 - exp(-dt/tau))

    阀门特性：
        linear: f(x) = x  （x = actual_pct / 100）
        equal_percentage: f(x) = R^(x-1)  （R = rangeability）
        流量 = max_flow * f(x)
    """

    def __init__(
        self,
        name: str,
        full_travel_time_s: float,
        characteristic: Literal["linear", "equal_percentage"],
        max_flow_kgmol_per_s: float,
        initial_command_pct: float = 50.0,
        rangeability: float = 30.0,
    ) -> None:
        if full_travel_time_s <= 0.0:
            raise ValueError(f"{name}: full_travel_time_s 必须>0，实际值={full_travel_time_s}")
        if characteristic not in ("linear", "equal_percentage"):
            raise ValueError(
                f"{name}: characteristic 必须为 'linear' 或 'equal_percentage'，"
                f"实际值={characteristic}"
            )
        if max_flow_kgmol_per_s <= 0.0:
            raise ValueError(
                f"{name}: max_flow_kgmol_per_s 必须>0，实际值={max_flow_kgmol_per_s}"
            )
        if not (0.0 <= initial_command_pct <= 100.0):
            raise ValueError(
                f"{name}: initial_command_pct 必须位于 [0, 100]，实际值={initial_command_pct}"
            )
        if rangeability <= 1.0:
            raise ValueError(f"{name}: rangeability 必须>1，实际值={rangeability}")

        self.name = name
        self.full_travel_time_s = float(full_travel_time_s)
        self.characteristic = characteristic
        self.max_flow_kgmol_per_s = float(max_flow_kgmol_per_s)
        self.rangeability = float(rangeability)

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
        x = actual_pct / 100，返回流量比例。
        """
        x = max(0.0, min(1.0, x))
        if self.characteristic == "linear":
            return x
        # equal_percentage: f(x) = R^(x-1)
        # 在 x=0 时 f=1/R（极小但非 0），x=1 时 f=1
        return self.rangeability ** (x - 1.0)

    # ------------------------------------------------------------------
    def get_flow_kgmol_per_s(self) -> float:
        """根据 actual_pct 和特性计算实际流量 (kmol/s)。"""
        x = self.actual_pct / 100.0
        return self.max_flow_kgmol_per_s * self.characteristic_function(x)

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
