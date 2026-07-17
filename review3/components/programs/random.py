"""
随机数生成算法

生成在指定范围内随机变化的数值，支持最大步进限制。
使用 NumPy 优化性能。
"""

import numpy as np
from controller.instance import InstanceRegistry
from .base import BaseProgram


class RANDOM(BaseProgram):
    """
    随机数生成算法。

    特点：
    - 在 [L, H] 范围内生成随机数
    - 每次变化不超过 max_step（避免突变）
    - 输出：out（当前随机值）
    - 优化：使用 NumPy 预生成随机池提升性能
    """

    # 文档属性（用于网页展示）
    name = "random"
    chinese_name = "随机数生成器"
    doc = """
# 随机数生成算法

生成在指定范围内随机变化的数值，支持最大步进限制。

## 特点

- 在 [L, H] 范围内生成随机数
- 每次变化不超过 max_step（避免突变）
- 使用 NumPy 预生成技术（支持超大并发计算）

## 使用示例

```yaml
- name: random1
  type: RANDOM
  init_args:
    L: 0.0
    H: 100.0
    max_step: 3.0
  expression: random1.execute()
```
"""
    params_table = """
| 参数名 | 含义 | 初值/说明 |
|--------|------|------------|
| L | 随机数下界，init_args | 0.0 |
| H | 随机数上界，init_args | 100.0 |
| max_step | 最大步进，单次变化绝对值上限，init_args | 3.0 |
| out | 当前输出值，快照位号 | 由 execute() 每步在 [L,H] 内随机游走 |
"""

    # 需要存储的属性
    stored_attributes = ["out"]

    input_schema = []

    param_descriptions = {
        "out": "输出值(随机)",
    }

    # 默认参数
    default_params = {
        "L": 0.0,  # 最小值
        "H": 100.0,  # 最大值
        "max_step": 3.0,  # 最大步进（每次变化不超过此值）
    }

    # 内部随机池大小
    _POOL_SIZE = 10000

    def __init__(self, cycle_time: float, **kwargs):
        """
        初始化随机数生成器。
        """
        super().__init__(cycle_time, **kwargs)
        # 初始化输出值（在范围内随机）
        self.out = np.random.uniform(self.L, self.H)
        
        # 预生成随机池
        self._pool = np.random.uniform(self.L, self.H, size=self._POOL_SIZE)
        self._pool_idx = 0

    def _refresh_pool(self):
        """刷新随机池"""
        self._pool = np.random.uniform(self.L, self.H, size=self._POOL_SIZE)
        self._pool_idx = 0

    def execute(self) -> None:
        """
        执行一个周期，生成新的随机值。
        """
        # 从池中获取目标值
        if self._pool_idx >= self._POOL_SIZE:
            self._refresh_pool()
        
        target = self._pool[self._pool_idx]
        self._pool_idx += 1

        # 计算变化量，限制在 max_step 内
        change = target - self.out
        if abs(change) > self.max_step:
            change = self.max_step if change > 0 else -self.max_step

        # 更新输出值
        self.out += change

        # 确保在范围内（NumPy 的 clip 比内置 max/min 快）
        self.out = np.clip(self.out, self.L, self.H)


# 注册算法
if __name__ != "__main__":
    InstanceRegistry.register_algorithm("RANDOM", RANDOM)

