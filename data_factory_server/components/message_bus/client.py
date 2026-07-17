"""
消息客户端

简化消息发送接口
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from .bus import MessageBus
from components.utils.logger import get_logger

logger = get_logger()


class MessageClient:
    """
    消息客户端
    
    提供简化的消息发送接口
    """
    
    def __init__(self, bus: MessageBus, client_name: str = "default"):
        """
        初始化消息客户端
        
        Args:
            bus: 消息总线实例
            client_name: 客户端名称（用于日志）
        """
        self.bus = bus
        self.client_name = client_name
    
    def call(
        self,
        service: str,
        action: str,
        params: Dict[str, Any],
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        调用远程服务（同步）
        
        Args:
            service: 目标服务名称
            action: 操作类型
            params: 参数
            timeout: 超时时间（秒）
        
        Returns:
            响应数据
        
        Raises:
            TimeoutError: 超时
            Exception: 服务错误
        """
        try:
            logger.debug(
                f"Calling service: {service}.{action}, client={self.client_name}"
            )
            return self.bus.send_command(service, action, params, timeout)
        except Exception as e:
            logger.error(
                f"Failed to call service {service}.{action}: {e}",
                exc_info=True
            )
            raise
    
    def call_async(
        self,
        service: str,
        action: str,
        params: Dict[str, Any]
    ) -> str:
        """
        异步调用远程服务
        
        Args:
            service: 目标服务名称
            action: 操作类型
            params: 参数
        
        Returns:
            消息ID（可用于后续查询响应）
        """
        try:
            message_id = self.bus.send_command_async(service, action, params)
            logger.debug(
                f"Async call sent: {service}.{action}, "
                f"message_id={message_id}, client={self.client_name}"
            )
            return message_id
        except Exception as e:
            logger.error(
                f"Failed to send async call {service}.{action}: {e}",
                exc_info=True
            )
            raise
    
    def get_response(self, message_id: str, timeout: int = 30) -> Dict[str, Any]:
        """
        获取异步调用的响应
        
        Args:
            message_id: 消息ID
            timeout: 超时时间（秒）
        
        Returns:
            响应数据
        """
        try:
            return self.bus.get_response(message_id, timeout)
        except Exception as e:
            logger.error(
                f"Failed to get response for {message_id}: {e}",
                exc_info=True
            )
            raise
    
    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        发布事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        try:
            self.bus.publish_event(event_type, data)
            logger.debug(
                f"Event published: {event_type}, client={self.client_name}"
            )
        except Exception as e:
            logger.error(f"Failed to publish event {event_type}: {e}", exc_info=True)
            raise
    
    def discover(self, service: str) -> Optional[Dict[str, Any]]:
        """
        发现服务
        
        Args:
            service: 服务名称
        
        Returns:
            服务信息，如果不存在返回 None
        """
        return self.bus.discover_service(service)
    
    def list_services(self) -> list[str]:
        """列出所有已注册的服务"""
        return self.bus.list_services()
    
    def check_health(self, service: str) -> bool:
        """
        检查服务健康状态
        
        Args:
            service: 服务名称
        
        Returns:
            是否健康
        """
        return self.bus.check_health(service)
