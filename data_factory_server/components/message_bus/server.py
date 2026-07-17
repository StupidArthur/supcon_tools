"""
消息服务端

监听并处理来自消息总线的消息
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Dict, Any, Callable, Optional

from .bus import MessageBus
from .message import Message, MessageType
from components.utils.logger import get_logger

logger = get_logger()


class MessageServer:
    """
    消息服务端
    
    功能：
    - 监听命令队列
    - 处理消息并返回响应
    - 发送事件
    """
    
    def __init__(
        self,
        service_name: str,
        bus: MessageBus,
        handlers: Optional[Dict[str, Callable]] = None
    ):
        """
        初始化消息服务端
        
        Args:
            service_name: 服务名称
            bus: 消息总线实例
            handlers: 消息处理器字典 {action: handler_function}
        """
        self.service_name = service_name
        self.bus = bus
        self.handlers = handlers or {}
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._command_queue_key = (
            f"{bus.config.key_prefix}:service:{service_name}:commands"
        )
    
    def register_handler(
        self,
        action: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        """
        注册消息处理器
        
        Args:
            action: 操作类型
            handler: 处理函数，接收 payload，返回结果字典
        """
        self.handlers[action] = handler
        logger.info(f"Handler registered: {self.service_name}.{action}")
    
    def unregister_handler(self, action: str) -> None:
        """注销消息处理器"""
        if action in self.handlers:
            del self.handlers[action]
            logger.info(f"Handler unregistered: {self.service_name}.{action}")
    
    def start(self) -> None:
        """启动服务端"""
        if self._running:
            logger.warning(f"MessageServer already running: {self.service_name}")
            return
        
        # 注册服务
        self.bus.register_service(
            self.service_name,
            {"status": "running", "handlers": list(self.handlers.keys())}
        )
        
        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        logger.info(f"MessageServer started: {self.service_name}")
    
    def stop(self) -> None:
        """停止服务端"""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self.bus.unregister_service(self.service_name)
        logger.info(f"MessageServer stopped: {self.service_name}")
    
    def _message_loop(self) -> None:
        """消息处理循环"""
        while self._running:
            try:
                # 阻塞等待命令
                result = self.bus.redis.brpop(self._command_queue_key, timeout=1)
                
                if result:
                    _, message_json = result
                    self._handle_message(message_json)
                
                # 更新健康状态和心跳
                self.bus.update_health(self.service_name, "healthy")
                self.bus.update_service_heartbeat(self.service_name)
                
            except Exception as e:
                logger.error(f"Error in message loop: {e}", exc_info=True)
                time.sleep(0.1)
    
    def _handle_message(self, message_json: str) -> None:
        """处理单个消息"""
        try:
            message = Message.from_json(message_json)
            
            # 查找处理器
            handler = self.handlers.get(message.action)
            if not handler:
                logger.warning(
                    f"No handler for action: {self.service_name}.{message.action}"
                )
                if message.message_type == MessageType.REQUEST:
                    self._send_error_response(
                        message,
                        f"Unknown action: {message.action}"
                    )
                return
            
            # 执行处理器
            try:
                result = handler(message.payload)
                
                # 发送响应（如果是请求-响应模式）
                if message.message_type == MessageType.REQUEST:
                    response = message.create_response(result, "ok")
                    self._send_response(response)
                elif message.message_type == MessageType.COMMAND:
                    # 命令模式不需要响应，但可以记录日志
                    logger.debug(
                        f"Command executed: {self.service_name}.{message.action}"
                    )
                # 注意：send_command_async 现在发送的是 REQUEST 类型，所以会发送响应
            
            except Exception as e:
                logger.error(f"Handler error: {e}", exc_info=True)
                if message.message_type == MessageType.REQUEST:
                    self._send_error_response(message, str(e))
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Failed to handle message: {e}", exc_info=True)
    
    def _send_response(self, response: Message) -> None:
        """发送响应"""
        try:
            self.bus.redis.hset(
                self.bus._response_hash_key,
                response.request_id,
                response.to_json()
            )
            # 设置过期时间
            self.bus.redis.expire(
                self.bus._response_hash_key,
                self.bus.config.result_ttl
            )
            logger.debug(f"Response sent: message_id={response.request_id}")
        except Exception as e:
            logger.error(f"Failed to send response: {e}", exc_info=True)
    
    def _send_error_response(self, request: Message, error: str) -> None:
        """发送错误响应"""
        response = request.create_error_response(error)
        self._send_response(response)
    
    def publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        发布事件
        
        Args:
            event_type: 事件类型
            payload: 事件数据
        """
        self.bus.publish_event(event_type, payload, self.service_name)
