"""
圆柱水箱模型

基于托里拆利定律实现液位动态计算；入口流量由外部传入，便于水箱级联。
"""

import math

from controller.instance import InstanceRegistry
from .base import BaseProgram


class CYLINDRICAL_TANK(BaseProgram):
    """
    圆柱体水箱模型。

    物理模型：
    - 一个圆柱体的水箱
    - 入口体积流量由外部（如阀门 outlet_flow、上游水箱 outlet_flow）传入
    - 在水箱最低处有圆形出水口，出水流量与当前液位相关（托里拆利定律）
    """

    # 文档属性（用于网页展示）
    name = "cylindrical_tank"
    chinese_name = "圆柱水箱"
    doc = """
# 圆柱体水箱模型

基于托里拆利定律实现液位动态计算；入口流量由外部传入，便于与阀门或其它水箱级联。

## 物理模型

- 圆柱体水箱，液位均匀
- 入口体积流量 `inlet_flow`（m³/s）由 DSL 表达式从上游设备传入
- 底部出水口流量由托里拆利定律计算：`v = sqrt(2gh)`，出口体积流量 = `outlet_area * v`

## 使用示例（阀门 + 水箱）

```yaml
- name: source_flow
  type: VARIABLE
  expression: source_flow = 0.18
- name: valve1
  type: VALVE
  init_args:
    full_travel_time: 10.0
  expression: valve1.execute(target_opening=pid1.MV, inlet_flow=source_flow)
- name: tank1
  type: CYLINDRICAL_TANK
  init_args:
    height: 10.0
    radius: 1.0
    initial_level: 0.0
  expression: tank1.execute(inlet_flow=valve1.outlet_flow)
```

## 级联水箱

```yaml
- name: tank_upper
  type: CYLINDRICAL_TANK
  expression: tank_upper.execute(inlet_flow=valve1.outlet_flow)
- name: tank_lower
  type: CYLINDRICAL_TANK
  expression: tank_lower.execute(inlet_flow=tank_upper.outlet_flow)
```
"""
    params_table = """
| 参数名 | 含义 | 初值/说明 |
|--------|------|------------|
| height | 水箱高度（米），init_args | 2.0 |
| radius | 水箱半径（米），init_args | 0.5 |
| outlet_area | 出水口面积（平方米），init_args | 0.001 |
| initial_level | 初始水位（米），init_args | 0.0 |
| inlet_flow | 入口体积流量（m³/s），每周期 `execute(inlet_flow=...)` 传入，并写入快照 | 默认 0.0，常接阀门或上游水箱的 outlet_flow |
| level | 当前水位（米），运行中更新，快照位号 | 初始等于 initial_level |
| outlet_flow | 出口体积流量（m³/s），由托里拆利定律计算，快照位号 | 运行中计算，可接下游水箱 inlet_flow |
"""

    # 需要对外存储的属性
    stored_attributes = [
        "level",
        "inlet_flow",
        "outlet_flow",
        "height",
        "radius",
        "outlet_area",
        "initial_level",
    ]

    input_schema = [
        {"name": "inlet_flow", "type": "float", "connectable": True, "desc": "入口流量(m³/s)"},
    ]

    #: 各 stored 参数的中文描述（前端位号配置对话框）
    param_descriptions = {
        "level": "当前水位(m)",
        "inlet_flow": "入口流量(m³/s)",
        "outlet_flow": "出口流量(m³/s)",
        "height": "水箱高度(m)",
        "radius": "水箱半径(m)",
        "outlet_area": "出水口面积(m²)",
        "initial_level": "初始水位(m)",
    }

    # 重力加速度（米/秒²）
    GRAVITY = 9.81

    # 默认参数
    default_params = {
        "height": 2.0,  # 水箱高度（米）
        "radius": 0.5,  # 水箱半径（米）
        "outlet_area": 0.001,  # 出水口面积（平方米）
        "initial_level": 0.0,  # 初始水位（米）
    }

    def __init__(self, cycle_time: float, **kwargs):
        """
        初始化圆柱体水箱模型。

        Args:
            cycle_time: 控制器周期（秒）
            **kwargs: 其他参数
        """
        super().__init__(cycle_time, **kwargs)
        self.level = self.initial_level

        # 水箱底面积
        self.base_area = math.pi * self.radius ** 2

        self.inlet_flow = 0.0
        self.outlet_flow = 0.0

    def execute(self, inlet_flow: float = 0.0) -> None:
        """
        执行水箱模型计算。

        Args:
            inlet_flow: 入口体积流量（立方米/秒），非负
        """
        self.inlet_flow = max(0.0, float(inlet_flow))

        # 计算出水流量（立方米/秒），托里拆利：v = sqrt(2gh)
        if self.level > 0:
            outlet_velocity = math.sqrt(2 * self.GRAVITY * self.level)
            self.outlet_flow = self.outlet_area * outlet_velocity
        else:
            self.outlet_flow = 0.0

        net_flow = self.inlet_flow - self.outlet_flow

        volume_change = net_flow * self.cycle_time
        level_change = volume_change / self.base_area

        self.level += level_change
        self.level = max(0.0, min(self.height, self.level))


# 注册模型（如果直接导入此模块）
if __name__ != "__main__":
    InstanceRegistry.register_model("CYLINDRICAL_TANK", CYLINDRICAL_TANK)
