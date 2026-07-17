"""
场景1：命令-响应模式 - 完整示例

在一个进程中同时运行服务端和客户端，演示完整的交互流程。
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
    
    def handle_calculate(payload):
        a = payload.get("a", 0)
        b = payload.get("b", 0)
        result = a + b
        print(f"[服务端] 收到命令: calculate, payload: {payload}")
        print(f"[服务端] 计算结果: {result}")
        return {"result": result}
    
    server.register_handler("calculate", handle_calculate)
    server.start()
    
    try:
        print(f"[服务端] 已启动，服务名称: {service_name}")
        # 保持运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def run_client(bus, service_name: str):
    """运行客户端"""
    time.sleep(1)  # 等待服务端启动
    
    client = MessageClient(bus, "calculator_client")
    
    test_cases = [
        {"a": 10, "b": 20},
        {"a": 100, "b": 200},
        {"a": -5, "b": 15},
    ]
    
    for i, params in enumerate(test_cases, 1):
        print(f"\n[客户端] 请求 {i}: 计算 {params['a']} + {params['b']}")
        
        try:
            result = client.call(service_name, "calculate", params, timeout=10)
            print(f"[客户端] 收到响应: {result}")
            print(f"[客户端] 计算结果: {result.get('result', 'N/A')}")
        except Exception as e:
            print(f"[客户端] 请求失败: {e}")
        
        time.sleep(0.5)
    
    print("\n[客户端] 所有请求完成")


def main():
    """主函数"""
    # 创建消息总线配置
    config = BusConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        key_prefix="example_scenario1"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    service_name = "calculator_service"
    
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
        
        # 保持运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭...")
    finally:
        bus.close()
        print("已关闭")


if __name__ == "__main__":
    main()
