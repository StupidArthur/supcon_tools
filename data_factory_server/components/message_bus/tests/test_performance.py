"""
性能测试
"""
import time
import pytest
from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient


class TestPerformance:
    """性能测试"""
    
    def test_single_message_latency(self, bus):
        """测试单条消息延迟"""
        server = MessageServer("perf_service", bus)
        
        def handle_fast(payload):
            return {"result": "ok"}
        
        server.register_handler("fast", handle_fast)
        server.start()
        
        try:
            client = MessageClient(bus, "perf_client")
            
            # 预热
            for _ in range(10):
                client.call("perf_service", "fast", {})
            
            # 测试延迟
            latencies = []
            for _ in range(100):
                start = time.time()
                client.call("perf_service", "fast", {})
                latency = (time.time() - start) * 1000  # 转换为毫秒
                latencies.append(latency)
            
            avg_latency = sum(latencies) / len(latencies)
            p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]
            
            print(f"\n单条消息延迟:")
            print(f"  平均: {avg_latency:.2f}ms")
            print(f"  P99: {p99_latency:.2f}ms")
            print(f"  最小: {min(latencies):.2f}ms")
            print(f"  最大: {max(latencies):.2f}ms")
            
            # 断言：平均延迟应该小于 10ms（本地 Redis）
            assert avg_latency < 10, f"平均延迟 {avg_latency}ms 过高"
        finally:
            server.stop()
    
    def test_throughput(self, bus):
        """测试吞吐量"""
        server = MessageServer("throughput_service", bus)
        
        def handle_throughput(payload):
            return {"result": payload.get("value", 0)}
        
        server.register_handler("throughput", handle_throughput)
        server.start()
        
        try:
            client = MessageClient(bus, "throughput_client")
            
            # 测试吞吐量
            count = 1000
            start = time.time()
            
            for i in range(count):
                # 增加超时时间，避免高负载时超时
                client.call("throughput_service", "throughput", {"value": i}, timeout=60)
            
            elapsed = time.time() - start
            throughput = count / elapsed
            
            print(f"\n吞吐量测试 ({count} 条消息):")
            print(f"  总时间: {elapsed:.2f}s")
            print(f"  吞吐量: {throughput:.2f} msg/s")
            
            # 断言：吞吐量应该大于 100 msg/s
            assert throughput > 100, f"吞吐量 {throughput} msg/s 过低"
        finally:
            server.stop()
    
    def test_large_payload(self, bus):
        """测试大负载消息"""
        server = MessageServer("large_service", bus)
        
        def handle_large(payload):
            return {"size": len(payload.get("data", ""))}
        
        server.register_handler("large", handle_large)
        server.start()
        
        try:
            client = MessageClient(bus, "large_client")
            
            # 测试不同大小的负载
            sizes = [100, 1000, 10000, 100000]  # bytes
            
            for size in sizes:
                data = "x" * size
                start = time.time()
                result = client.call("large_service", "large", {"data": data})
                elapsed = (time.time() - start) * 1000
                
                assert result["size"] == size
                print(f"  {size} bytes: {elapsed:.2f}ms")
        finally:
            server.stop()
    
    def test_connection_pool_performance(self, bus_config):
        """测试连接池性能"""
        # 使用相同的 key_prefix，确保消息路由正确
        shared_prefix = "test_pool_perf"
        
        # 不使用连接池
        config_no_pool = BusConfig(
            redis_host=bus_config.redis_host,
            redis_port=bus_config.redis_port,
            redis_db=bus_config.redis_db,
            key_prefix=shared_prefix,
            use_connection_pool=False
        )
        
        # 使用连接池
        config_with_pool = BusConfig(
            redis_host=bus_config.redis_host,
            redis_port=bus_config.redis_port,
            redis_db=bus_config.redis_db,
            key_prefix=shared_prefix,
            use_connection_pool=True,
            connection_pool_size=10
        )
        
        bus_no_pool = MessageBus(config_no_pool)
        bus_with_pool = MessageBus(config_with_pool)
        
        try:
            # 创建服务端（使用其中一个总线，但 key_prefix 相同，所以都能收到消息）
            server = MessageServer("pool_service", bus_with_pool)
            
            def handle_pool(payload):
                return {"result": "ok"}
            
            server.register_handler("pool", handle_pool)
            server.start()
            
            try:
                # 等待服务端启动
                time.sleep(0.1)
                
                # 测试不使用连接池
                client_no_pool = MessageClient(bus_no_pool, "client_no_pool")
                start = time.time()
                for _ in range(100):
                    client_no_pool.call("pool_service", "pool", {})
                time_no_pool = time.time() - start
                
                # 测试使用连接池
                client_with_pool = MessageClient(bus_with_pool, "client_with_pool")
                start = time.time()
                for _ in range(100):
                    client_with_pool.call("pool_service", "pool", {})
                time_with_pool = time.time() - start
                
                print(f"\n连接池性能对比 (100 条消息):")
                print(f"  无连接池: {time_no_pool:.2f}s")
                print(f"  有连接池: {time_with_pool:.2f}s")
                if time_no_pool > 0:
                    print(f"  提升: {(1 - time_with_pool/time_no_pool)*100:.1f}%")
            finally:
                server.stop()
        finally:
            bus_no_pool.close()
            bus_with_pool.close()
