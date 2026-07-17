"""
测试脚本：验证两个订阅者都能收到消息
"""
import sys
from pathlib import Path
import threading
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageClient

# 用于记录收到的消息
received_messages_1 = []
received_messages_2 = []


def subscriber1(bus):
    """订阅者1"""
    def on_event(message):
        received_messages_1.append(message.payload)
        print(f"[订阅者1] 收到消息: {message.payload}")
    
    print("[订阅者1] 开始订阅...")
    bus.subscribe_events(["test_event"], on_event, timeout=5)


def subscriber2(bus):
    """订阅者2"""
    def on_event(message):
        received_messages_2.append(message.payload)
        print(f"[订阅者2] 收到消息: {message.payload}")
    
    print("[订阅者2] 开始订阅...")
    bus.subscribe_events(["test_event"], on_event, timeout=5)


def main():
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="test_subscribers"
    )
    
    # 为每个订阅者创建独立的 bus 实例
    bus1 = MessageBus(config)
    bus2 = MessageBus(config)
    publisher_bus = MessageBus(config)
    
    try:
        # 启动订阅者
        thread1 = threading.Thread(target=subscriber1, args=(bus1,), daemon=True)
        thread2 = threading.Thread(target=subscriber2, args=(bus2,), daemon=True)
        
        thread1.start()
        thread2.start()
        
        # 等待订阅建立
        print("等待订阅建立...")
        time.sleep(1.5)
        
        # 发布消息
        client = MessageClient(publisher_bus, "test_publisher")
        print("\n发布消息...")
        for i in range(3):
            client.publish("test_event", {"message": f"test_{i}"})
            time.sleep(0.2)
        
        # 等待消息处理
        time.sleep(2)
        
        # 检查结果
        print(f"\n订阅者1收到的消息数: {len(received_messages_1)}")
        print(f"订阅者2收到的消息数: {len(received_messages_2)}")
        
        if len(received_messages_1) == 3 and len(received_messages_2) == 3:
            print("✅ 测试通过：两个订阅者都收到了所有消息")
        else:
            print("❌ 测试失败：消息接收不完整")
            print(f"  订阅者1: {received_messages_1}")
            print(f"  订阅者2: {received_messages_2}")
        
    finally:
        bus1.close()
        bus2.close()
        publisher_bus.close()


if __name__ == "__main__":
    main()
