"""
PID控制算法

通用的PID（比例-积分-微分）控制算法。
"""

from controller.instance import InstanceRegistry
from .base import BaseProgram


class PID(BaseProgram):
    """
    PID控制算法。

    特点：
    - 输入：PV（过程变量）、SV（设定值）
    - 输出：MV（操作变量）
    - 参数：PB（比例带）、TI（积分时间）、TD（微分时间）、MODE（运行模式）
    """

    # 文档属性（用于网页展示）
    name = "pid"
    chinese_name = "PID控制器"
    doc = """
# PID控制算法

通用的PID（比例-积分-微分）控制算法，用于过程控制。

## 特点

- **输入**：PV（过程变量）、SV（设定值）
- **输出**：MV（操作变量）
- **控制方式**：比例项 + 积分项 + 微分项
- **MODE**：`1` 时按公式计算 MV；非 `1` 时本周期不执行 PID 运算（不更新 MV、积分与微分状态）。

## 控制公式

- 比例项：`p_term = PB * error`
- 积分项：`i_term = PB / TI * integral`（当 TI > 0 时）
- 微分项：`d_term = PB * TD * (error - last_error) / cycle_time`
- 输出：`MV = p_term + i_term + d_term`（限制在 [L, H] 范围内）

## 使用示例

```yaml
- name: pid1
  type: PID
  init_args:
    PB: 120
    TI: 30
    TD: 0.15
    SV: 1.0
    H: 100.0
    L: 0.0
    MODE: 1
  expression: pid1.execute(PV=tank1.level, SV=sin1.out)
```
"""
    params_table = """
| 参数名 | 含义 | 初值/说明 |
|--------|------|------------|
| PB | 比例带，控制器的比例增益参数，init_args | 12.0 |
| TI | 积分时间（秒），用于消除稳态误差，init_args | 30.0 |
| TD | 微分时间（秒），用于改善动态响应，init_args | 0.15 |
| PV | 过程变量，每周期可由 `execute(PV=...)` 更新，快照位号 | init_args 默认 0.0 |
| SV | 设定值，每周期可由 `execute(SV=...)` 更新，快照位号 | init_args 默认 0.0 |
| MV | 操作变量（控制器输出），运行中计算，快照位号 | init_args 默认 0.0 |
| H | 输出上限，MV 的最大值，init_args | 100.0 |
| L | 输出下限，MV 的最小值，init_args | 0.0 |
| MODE | 运行模式：`1` 执行 PID 运算；非 `1` 本周期跳过运算（MV 等不更新），init_args | 1 |
"""

    # 需要存储的属性
    stored_attributes = ["MV", "PV", "SV", "PB", "TI", "TD", "H", "L", "MODE"]

    param_descriptions = {
        "MV": "操作变量(输出值)",
        "PV": "过程变量(当前值)",
        "SV": "设定值(目标值)",
        "PB": "比例带",
        "TI": "积分时间(s)",
        "TD": "微分时间(s)",
        "H": "输出上限",
        "L": "输出下限",
        "MODE": "运行模式(1=运算,非1=本周期跳过)",
    }

    # 默认参数
    default_params = {
        "PB": 12.0,  # 比例带
        "TI": 30.0,  # 积分时间（秒）
        "TD": 0.15,  # 微分时间（秒）
        "PV": 0.0,  # 过程变量初始值
        "SV": 0.0,  # 设定值
        "MV": 0.0,  # 输出值初始值
        "H": 100.0,  # 输出上限
        "L": 0.0,  # 输出下限
        "MODE": 1,  # 1=执行 PID；非 1 本周期不运算
    }

    def __init__(self, cycle_time: float, **kwargs):
        """
        初始化PID算法。

        Args:
            cycle_time: 控制器周期（秒）
            **kwargs: 其他参数
        """
        super().__init__(cycle_time, **kwargs)
        # PID 内部状态
        self._last_error = 0.0
        self._integral = 0.0

    def execute(self, PV: float = None, SV: float = None, MODE: float = None) -> None:
        """
        执行 PID 计算。

        Args:
            PV: 过程变量（如果提供则更新）
            SV: 设定值（如果提供则更新）
            MODE: 若提供则覆盖本周期运行模式（否则使用实例属性 self.MODE）
        """
        if PV is not None:
            self.PV = PV
        if SV is not None:
            self.SV = SV
        if MODE is not None:
            self.MODE = MODE

        # MODE 非 1：不执行 PID 内部逻辑（不更新 MV、积分与微分状态）
        try:
            mode_val = float(self.MODE)
        except (TypeError, ValueError):
            mode_val = 1.0
        if mode_val != 1.0:
            return

        # 计算误差
        error = self.SV - self.PV

        # 比例项
        p_term = self.PB * error

        # 积分项
        self._integral += error * self.cycle_time
        i_term = self.PB / self.TI * self._integral if self.TI > 0 else 0.0

        # 微分项
        d_term = self.PB * self.TD * (error - self._last_error) / self.cycle_time
        self._last_error = error

        # 计算输出
        self.MV = p_term + i_term + d_term

        # 限制输出范围
        self.MV = max(self.L, min(self.H, self.MV))


# 注册算法（如果直接导入此模块）
if __name__ != "__main__":
    InstanceRegistry.register_algorithm("PID", PID)

