"""
场景4：服务注册与发现 - 客户端

发现服务，调用服务，监控服务健康状态。
"""
import sys
import os
from pathlib import Path
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageClient, ServiceRegistry


def run_client(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "data_service"
):
    """
    运行客户端
    
    Args:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        service_name: 目标服务名称
    """
    # 创建消息总线配置
    config = BusConfig(
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        key_prefix="example_scenario4"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建服务注册表
    registry = ServiceRegistry(bus)
    
    # 创建客户端
    client = MessageClient(bus, "discovery_client")
    
    try:
        # 等待服务注册
        print("等待服务注册...")
        time.sleep(1)
        
        # 发现服务
        service_info = registry.discover(service_name)
        if service_info:
            print(f"发现服务: {service_name}")
            print(f"服务信息: {service_info}")
        else:
            print(f"未找到服务: {service_name}")
            return
        
        # 检查服务健康状态
        is_healthy = registry.check_health(service_name)
        print(f"服务健康状态: {is_healthy}")
        
        # 获取服务详细信息
        full_info = registry.get_service_info(service_name)
        if full_info:
            print(f"服务详细信息: {full_info}")
        
        # 列出所有已注册的服务
        all_services = registry.list_all()
        print(f"所有已注册的服务: {all_services}")
        
        # 调用服务
        print(f"\n调用服务: process, 参数: {{'data': 'test_data'}}")
        result = client.call(service_name, "process", {"data": "test_data"}, timeout=10)
        print(f"收到响应: {result}")
        
        # 再次检查服务健康状态
        is_healthy = registry.check_health(service_name)
        print(f"\n服务健康状态: {is_healthy}")
        
    finally:
        bus.close()


if __name__ == "__main__":
    run_client()
