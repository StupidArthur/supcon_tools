"""ua_tpt_loop —— 把 ua_mocker 节点 → tpt 数据源 → tpt 位号 → 历史值 这条路径走通。

子模块：
- mocker_yaml: 解析 ua_mocker YAML 组态
- ua_client:   步骤 1，连 OPC UA Server 验证节点可达
- tpt_checker: 步骤 2/3/4，验证 tpt 端 ds / tag / 数据流
- checker:     4 步编排
- report:      报告渲染
"""

from .checker import check_loop
from .mocker_yaml import MockerSpec, MOCKER_TYPE_TO_TPT
from .report import (
    LoopResult,
    StepResult,
    format_loop_report,
    format_step_line,
)
from .tpt_checker import (
    TptDsCheckResult,
    TptFlowCheckResult,
    TptTagsCheckResult,
    check_tpt_data_flow,
    check_tpt_ds,
    check_tpt_tags,
)
from .ua_client import UaCheckResult, check_ua_server, connect_endpoint

__version__ = "0.1.0"
__all__ = [
    "check_loop",
    "MockerSpec",
    "MOCKER_TYPE_TO_TPT",
    "LoopResult",
    "StepResult",
    "format_loop_report",
    "format_step_line",
    "TptDsCheckResult",
    "TptTagsCheckResult",
    "TptFlowCheckResult",
    "check_tpt_ds",
    "check_tpt_tags",
    "check_tpt_data_flow",
    "UaCheckResult",
    "check_ua_server",
    "connect_endpoint",
]
