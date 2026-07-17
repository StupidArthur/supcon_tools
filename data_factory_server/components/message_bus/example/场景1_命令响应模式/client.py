"""
场景1：命令-响应模式 - 客户端

向计算服务发送请求并等待响应。
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageClient
import time


def run_client(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "calculator_service"
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
        key_prefix="example_scenario1"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建客户端
    client = MessageClient(bus, "calculator_client")
    
    try:
        # 发送多个计算请求
        test_cases = [
            {"a": 10, "b": 20},
            {"a": 100, "b": 200},
            {"a": -5, "b": 15},
        ]
        
        for i, params in enumerate(test_cases, 1):
            print(f"\n请求 {i}: 计算 {params['a']} + {params['b']}")
            
            try:
                # 同步调用服务
                result = client.call(
                    service_name,
                    "calculate",
                    params,
                    timeout=10
                )
                
                print(f"收到响应: {result}")
                print(f"计算结果: {result.get('result', 'N/A')}")
                
            except Exception as e:
                print(f"请求失败: {e}")
            
            # 短暂延迟，避免请求过快
            time.sleep(0.5)
        
        print("\n所有请求完成")
        
    finally:
        bus.close()


if __name__ == "__main__":
    run_client()
