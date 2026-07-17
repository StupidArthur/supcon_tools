"""
阀门模型

模拟阀门的开度变化（有延迟），并根据入口流量与当前开度计算出口流量。
"""

from controller.instance import InstanceRegistry
from .base import BaseProgram


class VALVE(BaseProgram):
    """
    阀门模型。

    特点：
    - 有目标开度（target_opening）和当前开度（current_opening）
    - 当前开度会逐渐向目标开度移动（有延迟）
    - 移动速度由 full_travel_time 控制（满行程时间）
    - 出口流量 = flow_coefficient * inlet_flow * 开度比例（0~1）
    """

    # 文档属性（用于网页展示）
    name = "valve"
    chinese_name = "阀门"
    doc = """
# 阀门模型

模拟阀门的开度变化（有延迟），并根据入口流量与当前开度计算出口流量。

## 特点

- 有目标开度（target_opening）和当前开度（current_opening）
- 当前开度会逐渐向目标开度移动（有延迟）
- 移动速度由 full_travel_time 控制（满行程时间）
- `outlet_flow = flow_coefficient * inlet_flow * opening_ratio`，其中 opening_ratio 为当前开度在 min~max 之间的归一化比例

## 使用示例

```yaml
- name: source_flow
  type: VARIABLE
  expression: source_flow = 0.18
- name: valve1
  type: VALVE
  init_args:
    min_opening: 0.0
    max_opening: 100.0
    full_travel_time: 10.0
    initial_opening: 0.0
    flow_coefficient: 1.0
  expression: valve1.execute(target_opening=pid1.MV, inlet_flow=source_flow)
```
"""
    params_table = """
| 参数名 | 含义 | 初值/说明 |
|--------|------|------------|
| min_opening | 最小开度（%），init_args | 0.0 |
| max_opening | 最大开度（%），init_args | 100.0 |
| full_travel_time | 满行程时间（秒），从最小到最大开度所需时间，init_args | 10.0 |
| initial_opening | 初始开度（%），init_args | 0.0 |
| flow_coefficient | 流量系数，满开时出口相对入口的等效比例，init_args | 1.0 |
| target_opening | 目标开度（%），每周期可由 `execute(target_opening=...)` 更新，快照位号 | 初始为 initial_opening |
| current_opening | 当前开度（%），按行程速度向目标逼近，快照位号 | 初始为 initial_opening |
| inlet_flow | 入口体积流量（m³/s），每周期 `execute(inlet_flow=...)` 传入，快照位号 | 默认 0.0 |
| outlet_flow | 出口体积流量（m³/s），flow_coefficient×inlet_flow×开度比例，快照位号 | 运行中计算 |
"""

    # 需要存储的属性
    stored_attributes = [
        "current_opening",
        "target_opening",
        "inlet_flow",
        "outlet_flow",
        "flow_coefficient",
        "min_opening",
        "max_opening",
        "full_travel_time",
        "initial_opening",
    ]

    input_schema = [
        {"name": "target_opening", "type": "float", "connectable": True, "desc": "目标开度(%)"},
        {"name": "inlet_flow", "type": "float", "connectable": True, "desc": "入口流量(m³/s)"},
    ]

    param_descriptions = {
        "current_opening": "当前开度(%)",
        "target_opening": "目标开度(%)",
        "inlet_flow": "入口流量(m³/s)",
        "outlet_flow": "出口流量(m³/s)",
        "flow_coefficient": "流量系数",
        "min_opening": "最小开度(%)",
        "max_opening": "最大开度(%)",
        "full_travel_time": "满行程时间(s)",
        "initial_opening": "初始开度(%)",
    }

    # 默认参数
    default_params = {
        "min_opening": 0.0,  # 最小开度（%）
        "max_opening": 100.0,  # 最大开度（%）
        "full_travel_time": 10.0,  # 满行程时间（秒）
        "initial_opening": 0.0,  # 初始开度（%）
        "flow_coefficient": 1.0,  # 流量系数
    }

    def __init__(self, cycle_time: float, **kwargs):
        """
        初始化阀门模型。

        Args:
            cycle_time: 控制器周期（秒）
            **kwargs: 其他参数
        """
        super().__init__(cycle_time, **kwargs)
        self.current_opening = self.initial_opening
        self.target_opening = self.initial_opening
        self.inlet_flow = 0.0
        self.outlet_flow = 0.0

    def execute(self, target_opening: float = None, inlet_flow: float = 0.0) -> None:
        """
        执行阀门模型计算。

        Args:
            target_opening: 目标开度（%），范围 min_opening ~ max_opening
            inlet_flow: 入口体积流量（立方米/秒），非负
        """
        if target_opening is not None:
            self.target_opening = max(self.min_opening, min(self.max_opening, target_opening))

        max_range = self.max_opening - self.min_opening
        if self.full_travel_time > 0 and max_range > 0:
            speed = max_range / self.full_travel_time
        else:
            speed = float("inf")

        distance = speed * self.cycle_time

        diff = self.target_opening - self.current_opening
        if abs(diff) <= distance:
            self.current_opening = self.target_opening
        else:
            if diff > 0:
                self.current_opening += distance
            else:
                self.current_opening -= distance

        self.current_opening = max(self.min_opening, min(self.max_opening, self.current_opening))

        self.inlet_flow = max(0.0, float(inlet_flow))
        span = max(self.max_opening - self.min_opening, 1e-9)
        opening_ratio = (self.current_opening - self.min_opening) / span
        self.outlet_flow = self.flow_coefficient * self.inlet_flow * opening_ratio


# 注册模型（如果直接导入此模块）
if __name__ != "__main__":
    InstanceRegistry.register_model("VALVE", VALVE)
