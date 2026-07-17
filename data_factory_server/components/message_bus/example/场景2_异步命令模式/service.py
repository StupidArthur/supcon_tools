"""
场景2：异步命令模式 - 服务端

提供数据处理服务，模拟耗时操作。
"""
import sys
import os
from pathlib import Path
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageServer


def run_service(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "data_processor_service"
):
    """
    运行数据处理服务
    
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
        key_prefix="example_scenario2"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建服务端
    server = MessageServer(service_name, bus)
    
    # 注册数据处理处理器
    def handle_process_data(payload):
        """
        处理数据（模拟耗时操作）
        
        Args:
            payload: 包含 'data' 字段的字典
        
        Returns:
            包含处理结果的字典
        """
        data = payload.get("data", "")
        
        print(f"收到命令: process_data, payload: {payload}")
        print(f"正在处理数据: {data} (耗时 2 秒)")
        
        # 模拟耗时操作
        time.sleep(2)
        
        result = f"{data}_processed"
        print(f"处理完成: {result}")
        
        return {"result": result}
    
    # 注册处理器
    server.register_handler("process_data", handle_process_data)
    
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
