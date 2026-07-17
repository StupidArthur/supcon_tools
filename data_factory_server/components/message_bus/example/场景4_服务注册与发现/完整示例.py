"""
场景4：服务注册与发现 - 完整示例

在一个进程中同时运行服务端和客户端，演示服务注册与发现的完整流程。
"""
import sys
import os
from pathlib import Path
import threading
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient, ServiceRegistry


def run_service(bus, service_name: str):
    """运行服务端"""
    registry = ServiceRegistry(bus)
    
    # 注册服务
    registry.register(
        service_name,
        metadata={
            "version": "1.0.0",
            "description": "数据处理服务",
            "capabilities": ["process", "validate"]
        }
    )
    print(f"[服务端] 服务已注册: {service_name}")
    
    server = MessageServer(service_name, bus)
    
    def handle_process(payload):
        data = payload.get("data", "")
        result = f"{data}_processed"
        print(f"[服务端] 收到命令: process, payload: {payload}")
        print(f"[服务端] 处理结果: {result}")
        return {"result": result}
    
    server.register_handler("process", handle_process)
    server.start()
    
    try:
        print(f"[服务端] 服务端已启动，服务名称: {service_name}")
        while True:
            time.sleep(5)
            registry.update_heartbeat(service_name)
            registry.update_health(service_name, "healthy")
    except KeyboardInterrupt:
        pass
    finally:
        registry.unregister(service_name)
        server.stop()


def run_client(bus, service_name: str):
    """运行客户端"""
    time.sleep(1)  # 等待服务注册
    
    registry = ServiceRegistry(bus)
    client = MessageClient(bus, "discovery_client")
    
    # 发现服务
    service_info = registry.discover(service_name)
    if service_info:
        print(f"[客户端] 发现服务: {service_name}")
        print(f"[客户端] 服务信息: {service_info}")
    else:
        print(f"[客户端] 未找到服务: {service_name}")
        return
    
    # 检查服务健康状态
    is_healthy = registry.check_health(service_name)
    print(f"[客户端] 服务健康状态: {is_healthy}")
    
    # 获取服务详细信息
    full_info = registry.get_service_info(service_name)
    if full_info:
        print(f"[客户端] 服务详细信息: {full_info}")
    
    # 列出所有已注册的服务
    all_services = registry.list_all()
    print(f"[客户端] 所有已注册的服务: {all_services}")
    
    # 调用服务
    print(f"\n[客户端] 调用服务: process, 参数: {{'data': 'test_data'}}")
    result = client.call(service_name, "process", {"data": "test_data"}, timeout=10)
    print(f"[客户端] 收到响应: {result}")
    
    # 再次检查服务健康状态
    is_healthy = registry.check_health(service_name)
    print(f"\n[客户端] 服务健康状态: {is_healthy}")


def main():
    """主函数"""
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="example_scenario4"
    )
    
    bus = MessageBus(config)
    service_name = "data_service"
    
    try:
        # 在后台线程运行服务端
        server_thread = threading.Thread(
            target=run_service,
            args=(bus, service_name),
            daemon=True
        )
        server_thread.start()
        
        # 在主线程运行客户端
        run_client(bus, service_name)
        
        print("\n按 Ctrl+C 停止服务...")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭...")
    finally:
        bus.close()
        print("已关闭")


if __name__ == "__main__":
    main()
