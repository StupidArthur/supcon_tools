"""
消息总线配置
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BusConfig:
    """
    消息总线配置
    
    Attributes:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码（可选）
        key_prefix: Redis Key 前缀，默认 "message_bus"
        use_connection_pool: 是否使用连接池
        connection_pool_size: 连接池大小（如果启用连接池）
        result_ttl: 响应结果过期时间（秒）
    """
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    key_prefix: str = "message_bus"
    use_connection_pool: bool = False
    connection_pool_size: int = 10
    result_ttl: int = 60
