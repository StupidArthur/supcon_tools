"""
基于 Redis 的消息中间件

提供统一的消息传递接口，支持：
- 命令-响应模式（Request-Response）
- 发布-订阅模式（Pub/Sub）
- 事件驱动模式（Event-Driven）
- 服务发现（Service Discovery）
- 健康检查（Health Check）
"""

# 使用相对导入，避免模块路径问题
from .bus import MessageBus, BusConfig
from .client import MessageClient
from .server import MessageServer
from .message import Message, MessageType
from .registry import ServiceRegistry

__all__ = [
    "MessageBus",
    "BusConfig",
    "MessageClient",
    "MessageServer",
    "Message",
    "MessageType",
    "ServiceRegistry",
]
