"""
场景1：命令-响应模式 - 服务端

提供计算服务，接收两个数字并返回它们的和。
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageServer
import time


def run_service(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "calculator_service"
):
    """
    运行计算服务
    
    Args:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        service_name: 服务名称
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
    
    # 创建服务端
    server = MessageServer(service_name, bus)
    
    # 注册计算处理器
    def handle_calculate(payload):
        """
        处理计算请求
        
        Args:
            payload: 包含 'a' 和 'b' 两个数字的字典
        
        Returns:
            包含计算结果的字典
        """
        a = payload.get("a", 0)
        b = payload.get("b", 0)
        result = a + b
        
        print(f"收到命令: calculate, payload: {payload}")
        print(f"计算结果: {result}")
        
        return {"result": result}
    
    # 注册处理器
    server.register_handler("calculate", handle_calculate)
    
    # 启动服务
    server.start()
    
    try:
        print(f"服务端已启动，服务名称: {service_name}")
        print("等待命令... (按 Ctrl+C 停止)")
        
        # 保持运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭服务...")
    finally:
        server.stop()
        bus.close()
        print("服务已关闭")


if __name__ == "__main__":
    run_service()
