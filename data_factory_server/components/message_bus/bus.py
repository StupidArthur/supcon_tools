"""
核心消息总线

提供统一的消息传递接口
"""
from __future__ import annotations

import json
import time
from typing import Dict, Any, Optional, List, Callable

import redis
from redis.connection import ConnectionPool

from .config import BusConfig
from .message import Message, MessageType
from components.utils.logger import get_logger

logger = get_logger()


class MessageBus:
    """
    消息总线核心类
    
    功能：
    - 消息路由
    - 服务注册与发现
    - 健康检查
    - 消息持久化（可选）
    """
    
    def __init__(self, config: BusConfig):
        self.config = config
        self._redis: Optional[redis.Redis] = None
        self._connection_pool: Optional[ConnectionPool] = None
        self._active_pubsubs: set = set()  # 跟踪活动的 Pub/Sub 连接
        self._closed = False  # 标记是否已关闭
        self._init_redis()
        
        # Key 定义
        self._command_queue_prefix = f"{config.key_prefix}:service"
        self._response_hash_key = f"{config.key_prefix}:responses"
        self._event_channel_prefix = f"{config.key_prefix}:events"
        self._service_registry_key = f"{config.key_prefix}:services"
        self._health_key_prefix = f"{config.key_prefix}:health"
    
    def _init_redis(self) -> None:
        """初始化 Redis 连接"""
        try:
            if self.config.use_connection_pool:
                self._connection_pool = ConnectionPool(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    decode_responses=True,
                    max_connections=self.config.connection_pool_size,
                )
                self._redis = redis.Redis(connection_pool=self._connection_pool)
            else:
                self._redis = redis.Redis(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    decode_responses=True,
                )
            # 测试连接
            self._redis.ping()
            logger.info(
                "MessageBus initialized: redis=%s:%d/%d, prefix=%s",
                self.config.redis_host,
                self.config.redis_port,
                self.config.redis_db,
                self.config.key_prefix,
            )
        except Exception as e:
            logger.error(f"Failed to initialize MessageBus: {e}", exc_info=True)
            raise
    
    @property
    def redis(self) -> redis.Redis:
        """获取 Redis 客户端（供内部使用）"""
        if self._redis is None:
            raise RuntimeError("MessageBus not initialized")
        return self._redis
    
    # ========== 命令-响应模式 ==========
    
    def send_command(
        self,
        target_service: str,
        action: str,
        payload: Dict[str, Any],
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        发送命令并等待响应（同步）
        
        Args:
            target_service: 目标服务名称
            action: 操作类型
            payload: 消息载荷
            timeout: 超时时间（秒）
        
        Returns:
            响应数据
        
        Raises:
            TimeoutError: 超时
            Exception: 命令执行错误
        """
        message = Message(
            message_type=MessageType.REQUEST,
            service_name=target_service,
            action=action,
            payload=payload,
            ttl=timeout,
        )
        
        # 发送命令到目标服务的命令队列
        command_queue = f"{self._command_queue_prefix}:{target_service}:commands"
        try:
            self._redis.lpush(command_queue, message.to_json())
            logger.debug(
                "Command sent: %s.%s, message_id=%s",
                target_service,
                action,
                message.message_id,
            )
        except Exception as e:
            logger.error(f"Failed to send command: {e}", exc_info=True)
            raise
        
        # 等待响应（轮询）
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response_json = self._redis.hget(self._response_hash_key, message.message_id)
                
                if response_json:
                    response = Message.from_json(response_json)
                    
                    # 清理响应
                    self._redis.hdel(self._response_hash_key, message.message_id)
                    
                    if response.payload.get("status") == "error":
                        error_msg = response.payload.get("error", "Unknown error")
                        logger.error(f"Command error: {error_msg}")
                        raise Exception(error_msg)
                    
                    return response.payload.get("data", {})
                
                # 短暂休眠，避免 CPU 占用过高
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error waiting for response: {e}", exc_info=True)
                raise
        
        # 超时
        raise TimeoutError(
            f"Command timeout: {target_service}.{action}, "
            f"message_id={message.message_id}"
        )
    
    def send_command_async(
        self,
        target_service: str,
        action: str,
        payload: Dict[str, Any]
    ) -> str:
        """
        异步发送命令（不等待响应，但可以后续获取响应）
        
        注意：虽然名为"异步命令"，但实际发送的是 REQUEST 类型消息，
        这样服务端会发送响应，可以通过 get_response() 获取结果。
        
        Args:
            target_service: 目标服务名称
            action: 操作类型
            payload: 消息载荷
        
        Returns:
            消息ID（可用于后续查询响应）
        """
        # 使用 REQUEST 类型而不是 COMMAND，这样服务端会发送响应
        message = Message(
            message_type=MessageType.REQUEST,
            service_name=target_service,
            action=action,
            payload=payload,
        )
        
        command_queue = f"{self._command_queue_prefix}:{target_service}:commands"
        try:
            self._redis.lpush(command_queue, message.to_json())
            logger.debug(
                "Async command sent: %s.%s, message_id=%s",
                target_service,
                action,
                message.message_id,
            )
            return message.message_id
        except Exception as e:
            logger.error(f"Failed to send async command: {e}", exc_info=True)
            raise
    
    def get_response(self, message_id: str, timeout: int = 30) -> Dict[str, Any]:
        """
        获取异步命令的响应
        
        Args:
            message_id: 消息ID
            timeout: 超时时间（秒）
        
        Returns:
            响应数据
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            response_json = self._redis.hget(self._response_hash_key, message_id)
            if response_json:
                response = Message.from_json(response_json)
                self._redis.hdel(self._response_hash_key, message_id)
                
                if response.payload.get("status") == "error":
                    raise Exception(response.payload.get("error", "Unknown error"))
                
                return response.payload.get("data", {})
            
            time.sleep(0.01)
        
        raise TimeoutError(f"Response timeout: message_id={message_id}")
    
    # ========== 发布-订阅模式 ==========
    
    def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        target_service: Optional[str] = None
    ) -> None:
        """
        发布事件
        
        Args:
            event_type: 事件类型
            payload: 事件数据
            target_service: 目标服务（None 表示广播）
        """
        message = Message(
            message_type=MessageType.EVENT,
            service_name=target_service or "*",
            action=event_type,
            payload=payload,
        )
        
        # 发布到 Redis Pub/Sub
        if target_service:
            channel = f"{self._event_channel_prefix}:{target_service}:{event_type}"
        else:
            channel = f"{self._event_channel_prefix}:{event_type}"
        
        try:
            self._redis.publish(channel, message.to_json())
            logger.debug(f"Event published: {event_type}, channel={channel}")
        except Exception as e:
            logger.error(f"Failed to publish event: {e}", exc_info=True)
            raise
    
    def subscribe_events(
        self,
        event_types: List[str],
        callback: Callable[[Message], None],
        target_service: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> None:
        """
        订阅事件（阻塞调用）
        
        Args:
            event_types: 事件类型列表
            callback: 回调函数
            target_service: 目标服务（None 表示订阅所有）
            timeout: 超时时间（秒），None 表示无限等待
        """
        # 为每个订阅创建独立的 pubsub 对象，确保多个订阅者不会相互干扰
        pubsub = self._redis.pubsub()
        self._active_pubsubs.add(pubsub)
        
        try:
            # 订阅所有事件类型
            channels = []
            for event_type in event_types:
                if target_service:
                    channel = f"{self._event_channel_prefix}:{target_service}:{event_type}"
                else:
                    channel = f"{self._event_channel_prefix}:{event_type}"
                channels.append(channel)
                pubsub.subscribe(channel)
            
            # 等待订阅确认（读取订阅确认消息）
            # Redis 会在订阅后发送确认消息，需要先读取这些消息以确保订阅成功
            # 使用 ignore_subscribe_messages=False 来读取确认消息
            for _ in range(len(channels)):
                try:
                    msg = pubsub.get_message(timeout=2.0)
                    if msg:
                        if msg["type"] == "subscribe":
                            logger.debug(f"Subscription confirmed: {msg['channel']}")
                        # 如果是其他类型的消息，需要重新放回（不应该发生）
                except Exception as e:
                    logger.warning(f"Error reading subscription confirmation: {e}")
            
            logger.info(f"Subscribed to events: {event_types}, channels: {channels}")
            
            start_time = time.time()
            check_interval = 0.1  # 每 100ms 检查一次超时和关闭状态
            
            while True:
                # 检查是否已关闭
                if self._closed:
                    break
                
                # 检查超时
                if timeout and time.time() - start_time > timeout:
                    break
                
                try:
                    # 使用 get_message 而不是 listen，这样可以更好地控制
                    # ignore_subscribe_messages=True 会跳过订阅确认消息，只处理实际的消息
                    message = pubsub.get_message(timeout=check_interval, ignore_subscribe_messages=True)
                    if message and message["type"] == "message":
                        try:
                            msg = Message.from_json(message["data"])
                            callback(msg)
                        except Exception as e:
                            logger.error(f"Error handling event: {e}", exc_info=True)
                except (OSError, ValueError) as e:
                    # 连接已关闭
                    if self._closed:
                        break
                    logger.debug(f"Event subscription connection error: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error in event subscription: {e}", exc_info=True)
                    break
        except KeyboardInterrupt:
            logger.info("Event subscription stopped by user")
        except Exception as e:
            if not self._closed:
                logger.error(f"Error in event subscription: {e}", exc_info=True)
        finally:
            try:
                pubsub.close()
            except Exception:
                pass  # 忽略关闭时的错误
            finally:
                self._active_pubsubs.discard(pubsub)
    
    # ========== 服务注册与发现 ==========
    
    def register_service(
        self,
        service_name: str,
        metadata: Dict[str, Any]
    ) -> None:
        """
        注册服务
        
        Args:
            service_name: 服务名称
            metadata: 服务元数据（如版本、端点等）
        """
        service_info = {
            "name": service_name,
            "metadata": metadata,
            "registered_at": time.time(),
            "last_heartbeat": time.time(),
        }
        
        try:
            self._redis.hset(
                self._service_registry_key,
                service_name,
                json.dumps(service_info)
            )
            logger.info(f"Service registered: {service_name}")
        except Exception as e:
            logger.error(f"Failed to register service: {e}", exc_info=True)
            raise
    
    def unregister_service(self, service_name: str) -> None:
        """注销服务"""
        try:
            self._redis.hdel(self._service_registry_key, service_name)
            logger.info(f"Service unregistered: {service_name}")
        except Exception as e:
            logger.error(f"Failed to unregister service: {e}", exc_info=True)
    
    def discover_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """发现服务"""
        try:
            service_json = self._redis.hget(self._service_registry_key, service_name)
            if service_json:
                return json.loads(service_json)
            return None
        except Exception as e:
            logger.error(f"Failed to discover service: {e}", exc_info=True)
            return None
    
    def list_services(self) -> List[str]:
        """列出所有已注册的服务"""
        try:
            return list(self._redis.hkeys(self._service_registry_key))
        except Exception as e:
            logger.error(f"Failed to list services: {e}", exc_info=True)
            return []
    
    def update_service_heartbeat(self, service_name: str) -> None:
        """更新服务心跳"""
        try:
            service_json = self._redis.hget(self._service_registry_key, service_name)
            if service_json:
                service_info = json.loads(service_json)
                service_info["last_heartbeat"] = time.time()
                self._redis.hset(
                    self._service_registry_key,
                    service_name,
                    json.dumps(service_info)
                )
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {e}", exc_info=True)
    
    # ========== 健康检查 ==========
    
    def update_health(
        self,
        service_name: str,
        status: str = "healthy"
    ) -> None:
        """更新服务健康状态"""
        health_key = f"{self._health_key_prefix}:{service_name}"
        try:
            self._redis.setex(
                health_key,
                30,  # 30 秒过期
                json.dumps({
                    "status": status,
                    "timestamp": time.time(),
                })
            )
        except Exception as e:
            logger.error(f"Failed to update health: {e}", exc_info=True)
    
    def check_health(self, service_name: str) -> bool:
        """检查服务健康状态"""
        health_key = f"{self._health_key_prefix}:{service_name}"
        try:
            health_json = self._redis.get(health_key)
            if health_json:
                health = json.loads(health_json)
                return health.get("status") == "healthy"
            return False
        except Exception as e:
            logger.error(f"Failed to check health: {e}", exc_info=True)
            return False
    
    def close(self) -> None:
        """关闭连接"""
        self._closed = True
        
        try:
            # 先关闭所有活动的 Pub/Sub 连接
            for pubsub in list(self._active_pubsubs):
                try:
                    pubsub.close()
                except Exception:
                    pass  # 忽略关闭时的错误
            self._active_pubsubs.clear()
            
            # 然后关闭 Redis 连接
            if self._connection_pool:
                self._connection_pool.disconnect()
            elif self._redis:
                self._redis.close()
            logger.info("MessageBus connection closed")
        except Exception as e:
            logger.error(f"Failed to close MessageBus: {e}", exc_info=True)
