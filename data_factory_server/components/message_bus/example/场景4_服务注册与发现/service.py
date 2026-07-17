"""
场景4：服务注册与发现 - 服务端

启动时注册服务，提供数据处理功能。
"""
import sys
import os
from pathlib import Path
import time

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from components.message_bus import MessageBus, BusConfig, MessageServer, ServiceRegistry


def run_service(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    service_name: str = "data_service"
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
        key_prefix="example_scenario4"
    )
    
    # 创建消息总线
    bus = MessageBus(config)
    
    # 创建服务注册表
    registry = ServiceRegistry(bus)
    
    # 注册服务（带元数据）
    registry.register(
        service_name,
        metadata={
            "version": "1.0.0",
            "description": "数据处理服务",
            "capabilities": ["process", "validate"]
        }
    )
    print(f"服务已注册: {service_name}")
    
    # 创建服务端
    server = MessageServer(service_name, bus)
    
    # 注册处理器
    def handle_process(payload):
        """处理数据"""
        data = payload.get("data", "")
        result = f"{data}_processed"
        print(f"收到命令: process, payload: {payload}")
        print(f"处理结果: {result}")
        return {"result": result}
    
    server.register_handler("process", handle_process)
    
    # 启动服务
    server.start()
    
    try:
        print(f"服务端已启动，服务名称: {service_name}")
        print("等待命令... (按 Ctrl+C 停止)")
        
        # 定期更新心跳
        while True:
            time.sleep(5)
            registry.update_heartbeat(service_name)
            registry.update_health(service_name, "healthy")
            
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭服务...")
    finally:
        # 注销服务
        registry.unregister(service_name)
        server.stop()
        bus.close()
        print("服务已关闭")


if __name__ == "__main__":
    run_service()
