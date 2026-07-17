"""
TAG 信号程序

用于统一位号架构中的“可写输入 + 可读输出”场景。
"""

from controller.instance import InstanceRegistry
from .base import BaseProgram


class TAG(BaseProgram):
    """
    TAG 信号程序。

    设计目标：
    - 将可写入口统一为 ``in_value``，输出统一为 ``out``。
    - 每周期默认执行透传：``out = in_value``。
    - 支持在 execute 中通过 ``in_value`` 覆盖输入，便于在表达式里做连接。
    """

    name = "tag"
    chinese_name = "信号标签"
    doc = """
# TAG 信号程序

用于统一位号架构中的“可写输入 + 可读输出”场景。

## 特点

- 统一输入/输出位号：`in_value` 与 `out`
- 默认每周期透传：`out = in_value`
- 支持 `execute(in_value=...)` 在表达式中进行信号连接

## 使用示例

```yaml
- name: tag_setpoint
  type: TAG
  init_args:
    in_value: 1.0
  expression: tag_setpoint.execute()

- name: tag_copy
  type: TAG
  expression: tag_copy.execute(in_value=tag_setpoint.out)
```
"""
    params_table = """
| 参数名 | 含义 | 初值/说明 |
|--------|------|------------|
| in_value | 输入值，支持外部写值 | 0.0 |
| out | 输出值，默认透传 in_value | 0.0 |
"""

    stored_attributes = ["in_value", "out"]
    param_descriptions = {
        "in_value": "输入值",
        "out": "输出值",
    }
    default_params = {
        "in_value": 0.0,
        "out": 0.0,
    }

    def __init__(self, cycle_time: float, **kwargs):
        """初始化 TAG。"""
        super().__init__(cycle_time, **kwargs)
        # 若未显式设置 out，则默认与 in_value 保持一致
        if "out" not in kwargs:
            setattr(self, "out", float(getattr(self, "in_value", 0.0)))

    def execute(self, in_value=None) -> None:
        """
        执行一个周期。

        Args:
            in_value: 可选输入。提供时先更新 in_value，再执行 out = in_value。
        """
        if in_value is not None:
            setattr(self, "in_value", float(in_value))
        setattr(self, "out", float(getattr(self, "in_value", 0.0)))


if __name__ != "__main__":
    InstanceRegistry.register_algorithm("TAG", TAG)

