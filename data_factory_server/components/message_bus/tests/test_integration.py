"""
集成测试
"""
import time
import threading
import pytest
from components.message_bus import (
    MessageBus, BusConfig, MessageServer, MessageClient, ServiceRegistry
)


class TestIntegration:
    """集成测试"""
    
    def test_full_workflow(self, bus):
        """测试完整工作流程"""
        # 创建服务端
        server = MessageServer("workflow_service", bus)
        
        def handle_step1(payload):
            return {"step": 1, "data": payload["input"]}
        
        def handle_step2(payload):
            return {"step": 2, "data": payload["input"] * 2}
        
        server.register_handler("step1", handle_step1)
        server.register_handler("step2", handle_step2)
        server.start()
        
        try:
            # 创建客户端
            client = MessageClient(bus, "workflow_client")
            
            # 执行工作流
            result1 = client.call("workflow_service", "step1", {"input": 5})
            assert result1["step"] == 1
            assert result1["data"] == 5
            
            result2 = client.call("workflow_service", "step2", {"input": result1["data"]})
            assert result2["step"] == 2
            assert result2["data"] == 10
        finally:
            server.stop()
    
    def test_service_discovery_workflow(self, bus):
        """测试服务发现工作流"""
        registry = ServiceRegistry(bus)
        
        # 注册服务
        registry.register("discovery_service", {
            "version": "1.0.0",
            "endpoints": ["test"]
        })
        
        # 创建服务端
        server = MessageServer("discovery_service", bus)
        
        def handle_test(payload):
            return {"result": "ok"}
        
        server.register_handler("test", handle_test)
        server.start()
        
        try:
            # 发现服务
            service_info = registry.discover("discovery_service")
            assert service_info is not None
            
            # 检查健康状态
            registry.update_health("discovery_service", "healthy")
            assert registry.check_health("discovery_service")
            
            # 使用服务
            client = MessageClient(bus, "discovery_client")
            result = client.call("discovery_service", "test", {})
            assert result["result"] == "ok"
        finally:
            server.stop()
            registry.unregister("discovery_service")
    
    def test_event_driven_workflow(self, bus):
        """测试事件驱动工作流"""
        # 创建多个服务端
        server1 = MessageServer("event_service_1", bus)
        server2 = MessageServer("event_service_2", bus)
        
        events_received_1 = []
        events_received_2 = []
        
        def on_event_1(message):
            events_received_1.append(message.payload)
        
        def on_event_2(message):
            events_received_2.append(message.payload)
        
        # 订阅事件
        def subscribe_1():
            bus.subscribe_events(["workflow_event"], on_event_1, timeout=2.0)
        
        def subscribe_2():
            bus.subscribe_events(["workflow_event"], on_event_2, timeout=2.0)
        
        thread1 = threading.Thread(target=subscribe_1, daemon=True)
        thread2 = threading.Thread(target=subscribe_2, daemon=True)
        thread1.start()
        thread2.start()
        
        time.sleep(0.2)  # 等待订阅建立
        
        try:
            # 发布事件
            client = MessageClient(bus, "event_publisher")
            client.publish("workflow_event", {"step": "start"})
            client.publish("workflow_event", {"step": "process"})
            client.publish("workflow_event", {"step": "end"})
            
            time.sleep(0.5)  # 等待事件传递
            
            # 验证两个服务都收到了事件
            assert len(events_received_1) >= 3
            assert len(events_received_2) >= 3
        finally:
            server1.stop()
            server2.stop()
    
    def test_error_recovery(self, bus):
        """测试错误恢复"""
        server = MessageServer("recovery_service", bus)
        
        call_count = {"count": 0}
        
        def handle_recovery(payload):
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Temporary error")
            return {"result": "success"}
        
        server.register_handler("recovery", handle_recovery)
        server.start()
        
        try:
            client = MessageClient(bus, "recovery_client")
            
            # 前两次应该失败
            for _ in range(2):
                try:
                    client.call("recovery_service", "recovery", {})
                    assert False, "应该抛出异常"
                except Exception:
                    pass
            
            # 第三次应该成功
            result = client.call("recovery_service", "recovery", {})
            assert result["result"] == "success"
        finally:
            server.stop()
    
    def test_multiple_services_interaction(self, bus):
        """测试多个服务交互"""
        # 创建服务 A
        server_a = MessageServer("service_a", bus)
        
        def handle_a(payload):
            # 服务 A 调用服务 B
            client = MessageClient(bus, "service_a_client")
            result_b = client.call("service_b", "process", {"data": payload["data"]})
            return {"from_a": True, "from_b": result_b}
        
        server_a.register_handler("call_b", handle_a)
        server_a.start()
        
        # 创建服务 B
        server_b = MessageServer("service_b", bus)
        
        def handle_b(payload):
            return {"processed": payload["data"] * 2}
        
        server_b.register_handler("process", handle_b)
        server_b.start()
        
        try:
            # 客户端调用服务 A
            client = MessageClient(bus, "main_client")
            result = client.call("service_a", "call_b", {"data": 5})
            
            assert result["from_a"] is True
            assert result["from_b"]["processed"] == 10
        finally:
            server_a.stop()
            server_b.stop()
    
    def test_service_lifecycle(self, bus):
        """测试服务生命周期"""
        registry = ServiceRegistry(bus)
        
        # 1. 注册服务
        registry.register("lifecycle_service", {"version": "1.0.0"})
        assert registry.discover("lifecycle_service") is not None
        
        # 2. 启动服务
        server = MessageServer("lifecycle_service", bus)
        
        def handle_lifecycle(payload):
            return {"status": "running"}
        
        server.register_handler("status", handle_lifecycle)
        server.start()
        
        # 3. 使用服务
        client = MessageClient(bus, "lifecycle_client")
        result = client.call("lifecycle_service", "status", {})
        assert result["status"] == "running"
        
        # 4. 更新健康状态
        registry.update_health("lifecycle_service", "healthy")
        assert registry.check_health("lifecycle_service")
        
        # 5. 停止服务
        server.stop()
        registry.unregister("lifecycle_service")
        
        # 6. 验证服务不可用
        assert registry.discover("lifecycle_service") is None
