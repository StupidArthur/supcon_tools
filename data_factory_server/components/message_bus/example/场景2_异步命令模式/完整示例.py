"""
场景2：异步命令模式 - 完整示例

在一个进程中同时运行服务端和客户端，演示异步命令的完整流程。
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

from components.message_bus import MessageBus, BusConfig, MessageServer, MessageClient


def run_service(bus, service_name: str):
    """运行服务端"""
    server = MessageServer(service_name, bus)
    
    def handle_process_data(payload):
        data = payload.get("data", "")
        print(f"[服务端] 收到命令: process_data, payload: {payload}")
        print(f"[服务端] 正在处理数据: {data} (耗时 2 秒)")
        time.sleep(2)  # 模拟耗时操作
        result = f"{data}_processed"
        print(f"[服务端] 处理完成: {result}")
        return {"result": result}
    
    server.register_handler("process_data", handle_process_data)
    server.start()
    
    try:
        print(f"[服务端] 已启动，服务名称: {service_name}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def run_client(bus, service_name: str):
    """运行客户端"""
    time.sleep(1)  # 等待服务端启动
    
    client = MessageClient(bus, "data_processor_client")
    
    # 发送多个异步命令
    message_ids = []
    tasks = ["task1", "task2", "task3"]
    
    print("[客户端] 发送异步命令...")
    for i, task in enumerate(tasks, 1):
        message_id = client.call_async(service_name, "process_data", {"data": task})
        message_ids.append((i, message_id, task))
        print(f"[客户端] 发送异步命令 {i}: {task} (message_id: {message_id[:8]}...)")
    
    print("\n[客户端] 执行其他操作...")
    time.sleep(1)
    print("[客户端] 其他操作完成")
    
    print("\n[客户端] 获取异步命令的响应...")
    for i, message_id, task in message_ids:
        try:
            result = client.get_response(message_id, timeout=30)
            print(f"[客户端] 获取命令 {i} 的响应: {result}")
        except Exception as e:
            print(f"[客户端] 获取命令 {i} 的响应失败: {e}")
    
    print("\n[客户端] 所有异步命令处理完成")


def main():
    """主函数"""
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="example_scenario2"
    )
    
    bus = MessageBus(config)
    service_name = "data_processor_service"
    
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
