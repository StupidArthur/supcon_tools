"""
pytest conftest for standalone tests.

- 将项目根目录加入 sys.path，让测试函数可通过 ``from controller.xxx`` 顶层导入。
- 由于 ``tests/__init__.py`` 存在，pytest 默认不会把 tests/ 目录加入 sys.path，
  所以 ``from test_xxx import ...`` 这种 module-level 互引用需要 conftest 帮忙。
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 让测试间可以 ``from test_xxx import helper`` 风格互引
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
