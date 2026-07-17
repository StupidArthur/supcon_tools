"""
诊断框架基类

提供统一的诊断接口和推送机制
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json
import time

# redis 是可选依赖：standalone 模式不再强制安装；缺失时 push_diagnostics 自动 no-op
try:
    import redis  # type: ignore[import-untyped]
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False

from components.utils.logger import get_logger

logger = get_logger()


@dataclass
class DiagnosticItem:
    """诊断项定义"""
    name: str  # 诊断位号名
    value: Any  # 诊断值
    unit: str = ""  # 单位
    description: str = ""  # 描述
    data_type: str = "float"  # 数据类型：float, int, string, bool
    timestamp: float = None  # 时间戳

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "description": self.description,
            "data_type": self.data_type,
            "timestamp": self.timestamp,
        }


class DiagnosticProvider(ABC):
    """诊断提供者基类"""

    def __init__(self, service_name: str, redis_client: Optional[Any] = None):
        """
        初始化诊断提供者

        Args:
            service_name: 服务名称
            redis_client: Redis 客户端实例（可选）。
                          传 None 时 push_diagnostics 自动跳过（standalone 模式）。
        """
        self.service_name = service_name
        self.redis_client = redis_client
        self.diagnostic_key = f"data_factory:diagnostic:{service_name}"

    @abstractmethod
    def get_diagnostic_schema(self) -> Dict[str, Any]:
        """
        返回诊断结构定义

        Returns:
            诊断结构字典，包含：
            - items: 诊断项定义列表，每个项包含 name, unit, description, data_type
            - update_interval: 更新间隔（秒）
        """
        pass

    @abstractmethod
    def collect_diagnostics(self) -> List[DiagnosticItem]:
        """
        收集诊断数据

        Returns:
            诊断项列表
        """
        pass

    def push_diagnostics(self) -> None:
        """推送诊断信息到 Redis（standalone 模式下 redis_client 为 None，自动 no-op）"""
        if self.redis_client is None:
            logger.debug(
                "DiagnosticProvider[%s] 未配置 redis_client，跳过推送（standalone 模式）",
                self.service_name,
            )
            return
        try:
            diagnostics = self.collect_diagnostics()
            schema = self.get_diagnostic_schema()

            diagnostic_data = {
                "service_name": self.service_name,
                "schema": schema,
                "items": [item.to_dict() for item in diagnostics],
                "timestamp": time.time(),
            }

            json_str = json.dumps(diagnostic_data, ensure_ascii=False)
            self.redis_client.set(
                self.diagnostic_key,
                json_str,
                ex=300  # 5分钟过期，避免过期数据
            )

            logger.debug(f"推送诊断信息到 Redis: {self.service_name}, 键名: {self.diagnostic_key}, 项数: {len(diagnostics)}")
        except Exception as e:
            logger.error(f"推送诊断信息失败 ({self.service_name}): {e}", exc_info=True)

