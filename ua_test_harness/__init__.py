"""ua_test_harness -- UA 客户端(datahub)功能测试执行器后端(无 GUI)。

环境就绪链路:被测对象配置/登录 -> OS 检测 -> 起 ua-server-mock -> 数据源组态。
GUI 以后再做、再接这个后端。
"""
from . import _paths  # noqa: F401  设置 sys.path 复用 tpt_api / ua_tpt_manager

__version__ = "0.1.0"
