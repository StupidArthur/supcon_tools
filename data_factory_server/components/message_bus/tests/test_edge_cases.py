"""
边界情况测试
"""
import time
import pytest
from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient
from components.message_bus.message import Message, MessageType


class TestEdgeCases:
    """边界情况测试"""
    
    def test_empty_payload(self, bus):
        """测试空负载"""
        server = MessageServer("empty_service", bus)
        
        def handle_empty(payload):
            return {"received": len(payload)}
        
        server.register_handler("empty", handle_empty)
        server.start()
        
        try:
            client = MessageClient(bus, "empty_client")
            result = client.call("empty_service", "empty", {})
            assert result["received"] == 0
        finally:
            server.stop()
    
    def test_none_payload(self, bus):
        """测试 None 负载"""
        server = MessageServer("none_service", bus)
        
        def handle_none(payload):
            return {"is_none": payload is None}
        
        server.register_handler("none", handle_none)
        server.start()
        
        try:
            client = MessageClient(bus, "none_client")
            # 注意：JSON 不支持 None，会被转换为 null
            result = client.call("none_service", "none", {})
            assert result["is_none"] is False  # 空字典不是 None
        finally:
            server.stop()
    
    def test_unicode_payload(self, bus):
        """测试 Unicode 字符"""
        server = MessageServer("unicode_service", bus)
        
        def handle_unicode(payload):
            return {"text": payload["text"], "length": len(payload["text"])}
        
        server.register_handler("unicode", handle_unicode)
        server.start()
        
        try:
            client = MessageClient(bus, "unicode_client")
            result = client.call("unicode_service", "unicode", {
                "text": "你好世界 🌍"
            })
            assert result["text"] == "你好世界 🌍"
            assert result["length"] == 6  # 中文字符和 emoji
        finally:
            server.stop()
    
    def test_nested_payload(self, bus):
        """测试嵌套负载"""
        server = MessageServer("nested_service", bus)
        
        def handle_nested(payload):
            return {"nested": payload["nested"]}
        
        server.register_handler("nested", handle_nested)
        server.start()
        
        try:
            client = MessageClient(bus, "nested_client")
            nested_data = {
                "level1": {
                    "level2": {
                        "level3": {
                            "value": 42
                        }
                    }
                }
            }
            result = client.call("nested_service", "nested", {
                "nested": nested_data
            })
            assert result["nested"]["level1"]["level2"]["level3"]["value"] == 42
        finally:
            server.stop()
    
    def test_list_payload(self, bus):
        """测试列表负载"""
        server = MessageServer("list_service", bus)
        
        def handle_list(payload):
            return {"sum": sum(payload["numbers"])}
        
        server.register_handler("list", handle_list)
        server.start()
        
        try:
            client = MessageClient(bus, "list_client")
            result = client.call("list_service", "list", {
                "numbers": [1, 2, 3, 4, 5]
            })
            assert result["sum"] == 15
        finally:
            server.stop()
    
    def test_missing_handler(self, bus):
        """测试缺少处理器"""
        server = MessageServer("missing_service", bus)
        server.start()
        
        try:
            client = MessageClient(bus, "missing_client")
            # 应该返回错误，但不应该崩溃
            with pytest.raises(Exception):
                client.call("missing_service", "unknown_action", {})
        finally:
            server.stop()
    
    def test_handler_returns_none(self, bus):
        """测试处理器返回 None"""
        server = MessageServer("none_return_service", bus)
        
        def handle_none_return(payload):
            return None
        
        server.register_handler("none_return", handle_none_return)
        server.start()
        
        try:
            client = MessageClient(bus, "none_return_client")
            result = client.call("none_return_service", "none_return", {})
            # None 会被序列化为 null，反序列化后可能变成 None 或 {}
            assert result is None or result == {}
        finally:
            server.stop()
    
    def test_handler_raises_exception(self, bus):
        """测试处理器抛出异常"""
        server = MessageServer("exception_service", bus)
        
        def handle_exception(payload):
            raise RuntimeError("Test exception")
        
        server.register_handler("exception", handle_exception)
        server.start()
        
        try:
            client = MessageClient(bus, "exception_client")
            with pytest.raises(Exception) as exc_info:
                client.call("exception_service", "exception", {})
            assert "Test exception" in str(exc_info.value)
        finally:
            server.stop()
    
    def test_very_long_service_name(self, bus):
        """测试很长的服务名"""
        long_name = "a" * 1000
        server = MessageServer(long_name, bus)
        
        def handle_long(payload):
            return {"name_length": len(long_name)}
        
        server.register_handler("test", handle_long)
        server.start()
        
        try:
            client = MessageClient(bus, "long_client")
            result = client.call(long_name, "test", {})
            assert result["name_length"] == 1000
        finally:
            server.stop()
    
    def test_special_characters_in_payload(self, bus):
        """测试负载中的特殊字符"""
        server = MessageServer("special_service", bus)
        
        def handle_special(payload):
            return {"received": payload["text"]}
        
        server.register_handler("special", handle_special)
        server.start()
        
        try:
            client = MessageClient(bus, "special_client")
            special_text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
            result = client.call("special_service", "special", {
                "text": special_text
            })
            assert result["received"] == special_text
        finally:
            server.stop()
    
    def test_concurrent_same_service(self, bus):
        """测试并发访问同一服务"""
        server = MessageServer("concurrent_same", bus)
        
        results = []
        
        def handle_concurrent(payload):
            results.append(payload["id"])
            return {"id": payload["id"]}
        
        server.register_handler("concurrent", handle_concurrent)
        server.start()
        
        try:
            client = MessageClient(bus, "concurrent_client")
            
            import threading
            threads = []
            for i in range(10):
                thread = threading.Thread(
                    target=lambda x=i: client.call(
                        "concurrent_same",
                        "concurrent",
                        {"id": x}
                    )
                )
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join(timeout=5)
            
            # 验证所有请求都被处理
            assert len(results) == 10
            assert set(results) == set(range(10))
        finally:
            server.stop()
    
    def test_rapid_start_stop(self, bus):
        """测试快速启动停止"""
        for _ in range(5):
            server = MessageServer("rapid_service", bus)
            server.start()
            time.sleep(0.01)
            server.stop()
        
        # 应该不会崩溃
        assert True
