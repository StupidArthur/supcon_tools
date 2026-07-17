"""
测试消息总线核心功能
"""
import time
import pytest
from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient
from components.message_bus.message import MessageType


class TestMessageBus:
    """测试 MessageBus 类"""
    
    def test_bus_initialization(self, bus):
        """测试总线初始化"""
        assert bus is not None
        assert bus.redis is not None
    
    def test_send_and_receive_command(self, bus):
        """测试发送和接收命令"""
        # 创建服务端
        server = MessageServer("test_service", bus)
        
        def handle_test(payload):
            return {"result": payload["value"] * 2}
        
        server.register_handler("test", handle_test)
        server.start()
        
        try:
            # 创建客户端
            client = MessageClient(bus, "test_client")
            
            # 发送命令
            result = client.call("test_service", "test", {"value": 5})
            
            assert result["result"] == 10
        finally:
            server.stop()
    
    def test_command_timeout(self, bus):
        """测试命令超时"""
        # 创建服务端（不处理消息，模拟超时）
        server = MessageServer("slow_service", bus)
        
        def handle_slow(payload):
            time.sleep(2)  # 模拟慢操作
            return {"result": "done"}
        
        server.register_handler("slow", handle_slow)
        server.start()
        
        try:
            client = MessageClient(bus, "test_client")
            
            # 发送命令，超时时间很短
            with pytest.raises(TimeoutError):
                client.call("slow_service", "slow", {}, timeout=0.5)
        finally:
            server.stop()
    
    def test_async_command(self, bus):
        """测试异步命令"""
        server = MessageServer("test_service", bus)
        
        def handle_async(payload):
            return {"result": payload["value"]}
        
        server.register_handler("async", handle_async)
        server.start()
        
        try:
            client = MessageClient(bus, "test_client")
            
            # 发送异步命令
            message_id = client.call_async(
                "test_service",
                "async",
                {"value": 42}
            )
            
            assert message_id is not None
            
            # 稍后获取结果
            time.sleep(0.1)
            result = client.get_response(message_id, timeout=5)
            
            assert result["result"] == 42
        finally:
            server.stop()
    
    def test_publish_subscribe(self, bus):
        """测试发布-订阅"""
        received_messages = []
        
        def on_event(message):
            received_messages.append(message)
        
        # 订阅事件（在后台线程）
        import threading
        thread = threading.Thread(
            target=lambda: bus.subscribe_events(
                ["test_event"],
                on_event,
                timeout=1.0
            ),
            daemon=True
        )
        thread.start()
        
        time.sleep(0.1)  # 等待订阅建立
        
        # 发布事件
        client = MessageClient(bus, "publisher")
        client.publish("test_event", {"data": "test"})
        
        time.sleep(0.2)  # 等待消息传递
        
        assert len(received_messages) > 0
        assert received_messages[0].payload["data"] == "test"
    
    def test_service_registry(self, bus):
        """测试服务注册与发现"""
        # 注册服务
        bus.register_service("test_service", {
            "version": "1.0.0",
            "capabilities": ["test"]
        })
        
        # 发现服务
        service_info = bus.discover_service("test_service")
        assert service_info is not None
        assert service_info["metadata"]["version"] == "1.0.0"
        
        # 列出所有服务
        services = bus.list_services()
        assert "test_service" in services
        
        # 注销服务
        bus.unregister_service("test_service")
        service_info = bus.discover_service("test_service")
        assert service_info is None
    
    def test_health_check(self, bus):
        """测试健康检查"""
        # 更新健康状态
        bus.update_health("test_service", "healthy")
        
        # 检查健康状态
        assert bus.check_health("test_service") is True
        
        # 更新为不健康
        bus.update_health("test_service", "unhealthy")
        assert bus.check_health("test_service") is False
    
    def test_error_handling(self, bus):
        """测试错误处理"""
        server = MessageServer("error_service", bus)
        
        def handle_error(payload):
            raise ValueError("Test error")
        
        server.register_handler("error", handle_error)
        server.start()
        
        try:
            client = MessageClient(bus, "test_client")
            
            # 发送命令，应该收到错误响应
            with pytest.raises(Exception) as exc_info:
                client.call("error_service", "error", {})
            
            assert "Test error" in str(exc_info.value)
        finally:
            server.stop()
    
    def test_multiple_handlers(self, bus):
        """测试多个处理器"""
        server = MessageServer("multi_service", bus)
        
        def handle_a(payload):
            return {"result": "a"}
        
        def handle_b(payload):
            return {"result": "b"}
        
        server.register_handler("action_a", handle_a)
        server.register_handler("action_b", handle_b)
        server.start()
        
        try:
            client = MessageClient(bus, "test_client")
            
            result_a = client.call("multi_service", "action_a", {})
            assert result_a["result"] == "a"
            
            result_b = client.call("multi_service", "action_b", {})
            assert result_b["result"] == "b"
        finally:
            server.stop()
