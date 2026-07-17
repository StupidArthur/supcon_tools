"""
场景5：综合场景 - 完整示例

演示多个服务之间的交互，包括：
- 服务注册与发现
- 命令-响应模式
- 发布-订阅模式
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


def run_config_service(bus):
    """运行配置服务"""
    registry = ServiceRegistry(bus)
    registry.register("config_service", metadata={"version": "1.0.0"})
    print("[配置服务] 服务已注册: config_service")
    
    server = MessageServer("config_service", bus)
    
    def handle_load_config(payload):
        config_path = payload.get("config_path", "")
        print(f"[配置服务] 加载配置: {config_path}")
        return {"status": "loaded", "config_path": config_path}
    
    def handle_update_config(payload):
        config_path = payload.get("config_path", "")
        print(f"[配置服务] 更新配置: {config_path}")
        
        # 发布配置更新事件
        client = MessageClient(bus, "config_service")
        client.publish("config_updated", {"config_path": config_path})
        print("[配置服务] 发布配置更新事件")
        
        return {"status": "updated", "config_path": config_path}
    
    server.register_handler("load_config", handle_load_config)
    server.register_handler("update_config", handle_update_config)
    server.start()
    
    try:
        print("[配置服务] 服务端已启动")
        while True:
            time.sleep(5)
            registry.update_heartbeat("config_service")
            registry.update_health("config_service", "healthy")
    except KeyboardInterrupt:
        pass
    finally:
        registry.unregister("config_service")
        server.stop()


def run_data_service(bus):
    """运行数据服务"""
    registry = ServiceRegistry(bus)
    registry.register("data_service", metadata={"version": "1.0.0"})
    print("[数据服务] 服务已注册: data_service")
    
    server = MessageServer("data_service", bus)
    
    def handle_process_data(payload):
        data = payload.get("data", "")
        print(f"[数据服务] 处理数据: {data}")
        return {"result": f"{data}_processed"}
    
    server.register_handler("process_data", handle_process_data)
    server.start()
    
    # 订阅配置更新事件
    def on_config_updated(message):
        config_path = message.payload.get("config_path", "")
        print(f"[数据服务] 收到配置更新事件，执行配置重载: {config_path}")
    
    def subscribe_events():
        print("[数据服务] 已订阅事件: config_updated")
        bus.subscribe_events(["config_updated"], on_config_updated, timeout=None)
    
    subscribe_thread = threading.Thread(target=subscribe_events, daemon=True)
    subscribe_thread.start()
    
    try:
        print("[数据服务] 服务端已启动")
        while True:
            time.sleep(5)
            registry.update_heartbeat("data_service")
            registry.update_health("data_service", "healthy")
    except KeyboardInterrupt:
        pass
    finally:
        registry.unregister("data_service")
        server.stop()


def run_web_service(bus):
    """运行Web服务（客户端）"""
    time.sleep(2)  # 等待其他服务启动
    
    registry = ServiceRegistry(bus)
    client = MessageClient(bus, "web_service")
    
    # 发现配置服务
    config_info = registry.discover("config_service")
    if config_info:
        print("[Web服务] 发现配置服务")
        
        # 加载配置
        result = client.call("config_service", "load_config", {
            "config_path": "/path/to/config.yaml"
        }, timeout=10)
        print(f"[Web服务] 配置加载结果: {result}")
        
        # 更新配置
        result = client.call("config_service", "update_config", {
            "config_path": "/path/to/config.yaml"
        }, timeout=10)
        print(f"[Web服务] 配置更新结果: {result}")
    
    # 等待配置更新事件被处理
    time.sleep(1)
    
    # 发现数据服务
    data_info = registry.discover("data_service")
    if data_info:
        print("[Web服务] 发现数据服务")
        
        # 处理数据
        result = client.call("data_service", "process_data", {
            "data": "test_data"
        }, timeout=10)
        print(f"[Web服务] 数据处理结果: {result}")
    
    # 列出所有服务
    all_services = registry.list_all()
    print(f"[Web服务] 所有已注册的服务: {all_services}")


def main():
    """主函数"""
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="example_scenario5"
    )
    
    bus = MessageBus(config)
    
    try:
        # 在后台线程运行配置服务
        config_thread = threading.Thread(
            target=run_config_service,
            args=(bus,),
            daemon=True
        )
        config_thread.start()
        
        # 在后台线程运行数据服务
        data_thread = threading.Thread(
            target=run_data_service,
            args=(bus,),
            daemon=True
        )
        data_thread.start()
        
        # 在主线程运行Web服务
        run_web_service(bus)
        
        print("\n按 Ctrl+C 停止所有服务...")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭所有服务...")
    finally:
        bus.close()
        print("已关闭")


if __name__ == "__main__":
    main()
