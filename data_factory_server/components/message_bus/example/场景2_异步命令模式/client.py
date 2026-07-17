"""
场景2：异步命令模式 - 客户端

发送异步命令，不等待响应，可以继续执行其他操作。
"""
import sys
import os
from pathlib import Path
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageClient


def run_client(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "data_processor_service"
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
        key_prefix="example_scenario2"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建客户端
    client = MessageClient(bus, "data_processor_client")
    
    try:
        # 发送多个异步命令
        message_ids = []
        tasks = ["task1", "task2", "task3"]
        
        print("发送异步命令...")
        for i, task in enumerate(tasks, 1):
            message_id = client.call_async(
                service_name,
                "process_data",
                {"data": task}
            )
            message_ids.append((i, message_id, task))
            print(f"发送异步命令 {i}: {task} (message_id: {message_id[:8]}...)")
        
        print("\n执行其他操作...")
        time.sleep(1)
        print("其他操作完成")
        
        print("\n获取异步命令的响应...")
        for i, message_id, task in message_ids:
            try:
                # 获取响应（等待处理完成）
                result = client.get_response(message_id, timeout=30)
                print(f"获取命令 {i} 的响应: {result}")
            except Exception as e:
                print(f"获取命令 {i} 的响应失败: {e}")
        
        print("\n所有异步命令处理完成")
        
    finally:
        bus.close()


if __name__ == "__main__":
    run_client()
