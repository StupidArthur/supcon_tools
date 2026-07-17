"""
服务注册与发现

提供服务的注册、发现、健康检查等功能
"""
from __future__ import annotations

import json
import time
from typing import Dict, Any, Optional, List

from .bus import MessageBus
from components.utils.logger import get_logger

logger = get_logger()


class ServiceRegistry:
    """
    服务注册表
    
    管理服务的注册、发现和健康检查
    """
    
    def __init__(self, bus: MessageBus):
        """
        初始化服务注册表
        
        Args:
            bus: 消息总线实例
        """
        self.bus = bus
    
    def register(
        self,
        service_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        注册服务
        
        Args:
            service_name: 服务名称
            metadata: 服务元数据（如版本、端点、能力等）
        """
        metadata = metadata or {}
        self.bus.register_service(service_name, metadata)
    
    def unregister(self, service_name: str) -> None:
        """注销服务"""
        self.bus.unregister_service(service_name)
    
    def discover(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        发现服务
        
        Args:
            service_name: 服务名称
        
        Returns:
            服务信息，如果不存在返回 None
        """
        return self.bus.discover_service(service_name)
    
    def list_all(self) -> List[str]:
        """列出所有已注册的服务"""
        return self.bus.list_services()
    
    def update_heartbeat(self, service_name: str) -> None:
        """更新服务心跳"""
        self.bus.update_service_heartbeat(service_name)
    
    def update_health(
        self,
        service_name: str,
        status: str = "healthy"
    ) -> None:
        """
        更新服务健康状态
        
        Args:
            service_name: 服务名称
            status: 健康状态（healthy/unhealthy）
        """
        self.bus.update_health(service_name, status)
    
    def check_health(self, service_name: str) -> bool:
        """
        检查服务健康状态
        
        Args:
            service_name: 服务名称
        
        Returns:
            是否健康
        """
        return self.bus.check_health(service_name)
    
    def get_service_info(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        获取服务详细信息（包括健康状态）
        
        Args:
            service_name: 服务名称
        
        Returns:
            服务信息字典，包含：
            - name: 服务名称
            - metadata: 元数据
            - registered_at: 注册时间
            - last_heartbeat: 最后心跳时间
            - health: 健康状态
        """
        service_info = self.discover(service_name)
        if not service_info:
            return None
        
        service_info["health"] = self.check_health(service_name)
        return service_info
