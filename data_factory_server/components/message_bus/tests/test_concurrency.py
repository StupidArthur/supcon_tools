"""
并发测试
"""
import time
import threading
import pytest
from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient


class TestConcurrency:
    """并发测试"""
    
    def test_concurrent_requests(self, bus):
        """测试并发请求"""
        server = MessageServer("concurrent_service", bus)
        
        def handle_concurrent(payload):
            # 模拟一些处理时间
            time.sleep(0.01)
            return {"result": payload["value"]}
        
        server.register_handler("concurrent", handle_concurrent)
        server.start()
        
        try:
            client = MessageClient(bus, "concurrent_client")
            
            # 并发发送请求
            results = []
            errors = []
            
            def send_request(value):
                try:
                    result = client.call(
                        "concurrent_service",
                        "concurrent",
                        {"value": value}
                    )
                    results.append(result)
                except Exception as e:
                    errors.append(e)
            
            # 启动多个线程
            threads = []
            for i in range(50):
                thread = threading.Thread(target=send_request, args=(i,))
                threads.append(thread)
                thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join(timeout=10)
            
            # 验证结果
            assert len(errors) == 0, f"发生错误: {errors}"
            assert len(results) == 50, f"只收到 {len(results)} 个结果"
            
            # 验证结果正确性
            values = [r["result"] for r in results]
            assert set(values) == set(range(50)), "结果不完整"
        finally:
            server.stop()
    
    def test_concurrent_servers(self, bus):
        """测试多个服务端并发处理"""
        # 创建多个服务端
        servers = []
        for i in range(3):
            server = MessageServer(f"server_{i}", bus)
            
            def make_handler(server_id):
                def handle(payload):
                    return {"server": server_id, "value": payload["value"]}
                return handle
            
            server.register_handler("test", make_handler(i))
            server.start()
            servers.append(server)
        
        try:
            client = MessageClient(bus, "multi_client")
            
            # 向不同服务发送请求
            results = []
            for i in range(3):
                result = client.call(f"server_{i}", "test", {"value": i * 10})
                results.append(result)
            
            # 验证结果
            for i, result in enumerate(results):
                assert result["server"] == i
                assert result["value"] == i * 10
        finally:
            for server in servers:
                server.stop()
    
    def test_concurrent_clients(self, bus):
        """测试多个客户端并发发送"""
        server = MessageServer("multi_client_service", bus)
        
        def handle_multi(payload):
            return {"result": payload["client_id"]}
        
        server.register_handler("multi", handle_multi)
        server.start()
        
        try:
            # 创建多个客户端
            clients = []
            for i in range(5):
                client = MessageClient(bus, f"client_{i}")
                clients.append(client)
            
            # 并发发送请求
            results = []
            
            def send_from_client(client_id, client):
                for i in range(10):
                    result = client.call(
                        "multi_client_service",
                        "multi",
                        {"client_id": client_id}
                    )
                    results.append(result)
            
            threads = []
            for i, client in enumerate(clients):
                thread = threading.Thread(
                    target=send_from_client,
                    args=(i, client)
                )
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join(timeout=10)
            
            # 验证结果
            assert len(results) == 50
            client_ids = [r["result"] for r in results]
            assert set(client_ids) == set(range(5))
        finally:
            server.stop()
    
    def test_high_concurrency(self, bus):
        """测试高并发场景"""
        server = MessageServer("high_concurrent_service", bus)
        
        def handle_high(payload):
            return {"id": payload["id"]}
        
        server.register_handler("high", handle_high)
        server.start()
        
        try:
            client = MessageClient(bus, "high_client")
            
            # 高并发测试
            concurrent_count = 200
            results = []
            errors = []
            
            def send_high(id_value):
                try:
                    result = client.call(
                        "high_concurrent_service",
                        "high",
                        {"id": id_value},
                        timeout=5
                    )
                    results.append(result)
                except Exception as e:
                    errors.append((id_value, e))
            
            start = time.time()
            threads = []
            for i in range(concurrent_count):
                thread = threading.Thread(target=send_high, args=(i,))
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join(timeout=30)
            
            elapsed = time.time() - start
            
            print(f"\n高并发测试 ({concurrent_count} 并发):")
            print(f"  成功: {len(results)}")
            print(f"  失败: {len(errors)}")
            print(f"  总时间: {elapsed:.2f}s")
            print(f"  吞吐量: {len(results)/elapsed:.2f} msg/s")
            
            # 验证：至少 95% 的请求成功
            success_rate = len(results) / concurrent_count
            assert success_rate >= 0.95, f"成功率 {success_rate*100:.1f}% 过低"
            
            if errors:
                print(f"  错误示例: {errors[:5]}")
        finally:
            server.stop()
    
    def test_concurrent_async_commands(self, bus):
        """测试并发异步命令"""
        server = MessageServer("async_service", bus)
        
        def handle_async(payload):
            time.sleep(0.1)  # 模拟处理时间
            return {"id": payload["id"]}
        
        server.register_handler("async", handle_async)
        server.start()
        
        try:
            client = MessageClient(bus, "async_client")
            
            # 发送多个异步命令
            message_ids = []
            for i in range(20):
                message_id = client.call_async(
                    "async_service",
                    "async",
                    {"id": i}
                )
                message_ids.append(message_id)
            
            # 等待所有结果
            results = []
            for message_id in message_ids:
                result = client.get_response(message_id, timeout=10)
                results.append(result)
            
            # 验证结果
            assert len(results) == 20
            ids = [r["id"] for r in results]
            assert set(ids) == set(range(20))
        finally:
            server.stop()
    
    def test_race_condition(self, bus):
        """测试竞态条件"""
        server = MessageServer("race_service", bus)
        
        counter = {"value": 0}
        lock = threading.Lock()
        
        def handle_race(payload):
            with lock:
                counter["value"] += 1
                return {"counter": counter["value"]}
        
        server.register_handler("race", handle_race)
        server.start()
        
        try:
            client = MessageClient(bus, "race_client")
            
            # 并发增加计数器
            threads = []
            for _ in range(50):
                thread = threading.Thread(
                    target=lambda: client.call("race_service", "race", {})
                )
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join(timeout=10)
            
            # 验证计数器值
            final_result = client.call("race_service", "race", {})
            assert final_result["counter"] == 51  # 50 + 1
        finally:
            server.stop()
