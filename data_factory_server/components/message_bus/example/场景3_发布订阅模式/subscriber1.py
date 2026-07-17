"""
场景3：发布-订阅模式 - 订阅者1

订阅配置更新事件，执行配置重载。
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

from components.message_bus import MessageBus, BusConfig


def run_subscriber1(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0
):
    """
    运行订阅者1
    
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
    
    # 定义事件处理函数
    def on_config_updated(message):
        """
        处理配置更新事件
        
        Args:
            message: 消息对象
        """
        config_path = message.payload.get("config_path", "")
        print(f"[订阅者1] 收到事件: config_updated")
        print(f"[订阅者1] 执行配置重载: {config_path}")
        # 这里可以执行实际的配置重载逻辑
    
    # 在后台线程订阅事件
    def subscribe():
        print("[订阅者1] 已订阅事件: config_updated")
        # 使用 timeout=None 表示无限等待，直到 bus 关闭
        bus.subscribe_events(
            ["config_updated"],
            on_config_updated,
            timeout=None
        )
    
    subscribe_thread = threading.Thread(target=subscribe, daemon=True)
    subscribe_thread.start()
    
    try:
        print("[订阅者1] 已启动，等待事件... (按 Ctrl+C 停止)")
        
        # 保持运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭订阅者...")
    finally:
        bus.close()
        print("订阅者1已关闭")


if __name__ == "__main__":
    run_subscriber1()
