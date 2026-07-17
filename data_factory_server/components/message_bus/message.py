"""
消息格式定义

定义统一的消息格式，支持多种消息类型
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum

from components.utils.logger import get_logger

logger = get_logger()


class MessageType(Enum):
    """消息类型"""
    REQUEST = "request"      # 请求-响应模式
    RESPONSE = "response"    # 响应
    EVENT = "event"         # 事件（发布-订阅）
    COMMAND = "command"      # 命令（单向）


@dataclass
class Message:
    """
    统一消息格式
    
    Attributes:
        message_id: 消息唯一ID
        message_type: 消息类型
        service_name: 服务名称（发送方或目标服务）
        action: 操作类型
        payload: 消息载荷
        request_id: 请求ID（用于响应关联）
        timestamp: 时间戳
        ttl: 消息生存时间（秒）
    """
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: MessageType = MessageType.REQUEST
    service_name: str = ""
    action: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    ttl: int = 60
    
    def to_json(self) -> str:
        """序列化为 JSON"""
        try:
            return json.dumps({
                "message_id": self.message_id,
                "message_type": self.message_type.value,
                "service_name": self.service_name,
                "action": self.action,
                "payload": self.payload,
                "request_id": self.request_id,
                "timestamp": self.timestamp,
                "ttl": self.ttl,
            })
        except Exception as e:
            logger.error(f"Failed to serialize message: {e}", exc_info=True)
            raise
    
    @classmethod
    def from_json(cls, json_str: str) -> Message:
        """从 JSON 反序列化"""
        try:
            data = json.loads(json_str)
            return cls(
                message_id=data.get("message_id", str(uuid.uuid4())),
                message_type=MessageType(data.get("message_type", "request")),
                service_name=data.get("service_name", ""),
                action=data.get("action", ""),
                payload=data.get("payload", {}),
                request_id=data.get("request_id"),
                timestamp=data.get("timestamp", time.time()),
                ttl=data.get("ttl", 60),
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message JSON: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to deserialize message: {e}", exc_info=True)
            raise
    
    def create_response(
        self,
        payload: Dict[str, Any],
        status: str = "ok"
    ) -> Message:
        """创建响应消息"""
        return Message(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.RESPONSE,
            service_name=self.service_name,  # 响应给原服务
            action=self.action,
            payload={"status": status, "data": payload},
            request_id=self.message_id,  # 关联原请求
            timestamp=time.time(),
        )
    
    def create_error_response(self, error: str) -> Message:
        """创建错误响应消息"""
        return Message(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.RESPONSE,
            service_name=self.service_name,
            action=self.action,
            payload={"status": "error", "error": error},
            request_id=self.message_id,
            timestamp=time.time(),
        )
