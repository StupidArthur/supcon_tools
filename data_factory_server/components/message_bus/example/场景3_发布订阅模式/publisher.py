"""
场景3：发布-订阅模式 - 发布者

发布配置更新事件。
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


def run_publisher(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0
):
    """
    运行发布者
    
    Args:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
    """
    # 创建消息总线配置
    config = BusConfig(
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        key_prefix="example_scenario3"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建客户端（用于发布事件）
    client = MessageClient(bus, "config_publisher")
    
    try:
        # 等待订阅者启动
        print("等待订阅者启动...")
        time.sleep(2)
        
        # 发布多个配置更新事件
        config_paths = [
            "/path/to/config.yaml",
            "/path/to/config2.yaml",
        ]
        
        for config_path in config_paths:
            print(f"\n发布事件: config_updated, 数据: {{'config_path': '{config_path}'}}")
            client.publish("config_updated", {"config_path": config_path})
            time.sleep(1)
        
        print("\n所有事件已发布")
        print("等待订阅者处理... (按 Ctrl+C 退出)")
        
        # 保持运行，让订阅者有足够时间处理事件
        time.sleep(5)
        
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭...")
    finally:
        bus.close()
        print("发布者已关闭")


if __name__ == "__main__":
    run_publisher()
