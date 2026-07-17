"""
场景3：发布-订阅模式 - 完整示例

在一个进程中同时运行发布者和多个订阅者，演示事件驱动的完整流程。
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

from components.message_bus import MessageBus, BusConfig, MessageClient


def run_subscriber1(bus):
    """运行订阅者1（配置重载）"""
    def on_config_updated(message):
        config_path = message.payload.get("config_path", "")
        print(f"[订阅者1] 收到事件: config_updated")
        print(f"[订阅者1] 执行配置重载: {config_path}")
    
    print("[订阅者1] 已订阅事件: config_updated")
    # 使用 timeout=None 表示无限等待，直到 bus 关闭
    bus.subscribe_events(["config_updated"], on_config_updated, timeout=None)


def run_subscriber2(bus):
    """运行订阅者2（缓存清理）"""
    def on_config_updated(message):
        config_path = message.payload.get("config_path", "")
        print(f"[订阅者2] 收到事件: config_updated")
        print(f"[订阅者2] 执行缓存清理: {config_path}")
    
    print("[订阅者2] 已订阅事件: config_updated")
    # 使用 timeout=None 表示无限等待，直到 bus 关闭
    bus.subscribe_events(["config_updated"], on_config_updated, timeout=None)


def run_publisher(bus):
    """运行发布者"""
    time.sleep(1)  # 等待订阅者启动
    
    client = MessageClient(bus, "config_publisher")
    
    config_paths = [
        "/path/to/config.yaml",
        "/path/to/config2.yaml",
    ]
    
    for config_path in config_paths:
        print(f"\n[发布者] 发布事件: config_updated, 数据: {{'config_path': '{config_path}'}}")
        client.publish("config_updated", {"config_path": config_path})
        time.sleep(1)
    
    print("\n[发布者] 所有事件已发布")


def main():
    """主函数"""
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="example_scenario3"
    )
    
    # 为发布者创建独立的 bus 实例
    publisher_bus = MessageBus(config)
    
    # 为每个订阅者创建独立的 bus 实例（避免连接冲突）
    subscriber1_bus = MessageBus(config)
    subscriber2_bus = MessageBus(config)
    
    try:
        # 在后台线程运行订阅者（每个订阅者使用独立的 bus 实例）
        subscriber1_thread = threading.Thread(
            target=run_subscriber1,
            args=(subscriber1_bus,),
            daemon=True
        )
        subscriber1_thread.start()
        
        subscriber2_thread = threading.Thread(
            target=run_subscriber2,
            args=(subscriber2_bus,),
            daemon=True
        )
        subscriber2_thread.start()
        
        # 等待订阅者建立连接（给足够的时间让订阅确认完成）
        time.sleep(1.0)
        
        # 在主线程运行发布者
        run_publisher(publisher_bus)
        
        print("\n等待订阅者处理事件...")
        time.sleep(3)
        
        print("\n按 Ctrl+C 停止...")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭...")
    finally:
        publisher_bus.close()
        subscriber1_bus.close()
        subscriber2_bus.close()
        print("已关闭")


if __name__ == "__main__":
    main()
