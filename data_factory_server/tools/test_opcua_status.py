"""
测试 OPCUA Server 运行状态

检查 OPCUA Server 的实际运行状态，包括：
- _running 标志
- 服务器线程状态
- 异步事件循环状态
- 服务注册状态
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import redis
import json
from services.service_manager import ServiceManager, ServiceManagerConfig
from components.message_bus import MessageBus, BusConfig, ServiceRegistry
from components.utils.logger import get_logger

logger = get_logger()


def test_opcua_status():
    """测试 OPCUA Server 运行状态"""
    
    print("=" * 60)
    print("OPCUA Server 状态检查")
    print("=" * 60)
    
    # 尝试从web_backend导入service_manager（如果服务正在运行）
    print("\n0. 尝试从运行中的服务获取状态")
    print("-" * 60)
    
    try:
        # 尝试导入web_backend.main中的service_manager
        import importlib.util
        main_path = project_root / "web_backend" / "main.py"
        if main_path.exists():
            spec = importlib.util.spec_from_file_location("web_backend.main", main_path)
            if spec and spec.loader:
                # 注意：这会重新执行main.py，可能会启动新的服务
                # 所以我们需要通过API来检查
                print("[INFO] 检测到web_backend/main.py，建议通过API检查")
    except Exception as e:
        print(f"[WARNING] 无法导入web_backend.main: {e}")
    
    # 首先检查 Redis 中的服务注册信息
    print("\n1. 检查 Redis 中的服务注册信息")
    print("-" * 60)
    
    try:
        redis_client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
        )
        
        # 检查服务注册表
        registry_key = "service_manager:services"
        all_services = redis_client.hkeys(registry_key)
        print(f"所有已注册的服务: {all_services}")
        
        if "opcua_server" in all_services:
            service_info_json = redis_client.hget(registry_key, "opcua_server")
            service_info = json.loads(service_info_json)
            print(f"\nOPCUA Server 注册信息:")
            print(f"  - name: {service_info.get('name')}")
            print(f"  - metadata: {service_info.get('metadata')}")
            print(f"  - registered_at: {service_info.get('registered_at')}")
            print(f"  - last_heartbeat: {service_info.get('last_heartbeat')}")
        else:
            print("\n[WARNING] OPCUA Server 未在 Redis 中注册")
        
        # 检查健康状态
        health_key = "service_manager:health:opcua_server"
        health_info_json = redis_client.get(health_key)
        if health_info_json:
            health_info = json.loads(health_info_json)
            print(f"\nOPCUA Server 健康状态:")
            print(f"  - status: {health_info.get('status')}")
            print(f"  - timestamp: {health_info.get('timestamp')}")
        else:
            print("\n[WARNING] Redis 中没有找到 OPCUA Server 的健康状态")
            
    except Exception as e:
        print(f"[ERROR] 检查 Redis 时出错: {e}")
        import traceback
        traceback.print_exc()
    
    # 通过 ServiceManager 检查状态
    print("\n2. 通过 ServiceManager 检查状态")
    print("-" * 60)
    
    # 创建 ServiceManager（使用与主服务相同的配置）
    config = ServiceManagerConfig(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        enable_engine=True,
        enable_storage=True,
        enable_opcua=True,
    )
    
    manager = ServiceManager(config)
    
    # 获取诊断信息
    diagnostic = manager.get_diagnostic_info()
    print(f"opcua_running (诊断信息): {diagnostic.get('opcua_running')}")
    
    services_status = diagnostic.get('services_status', {})
    opcua_status = services_status.get('opcua_server', {})
    print(f"\nOPCUA Server 服务状态:")
    print(f"  - registered: {opcua_status.get('registered')}")
    print(f"  - health: {opcua_status.get('health')}")
    print(f"  - last_heartbeat: {opcua_status.get('last_heartbeat')}")
    
    # 检查 OPCUA Server 实例（如果存在）
    print("\n3. 检查 OPCUA Server 实例状态")
    print("-" * 60)
    
    if manager.opcua_server is None:
        print("[WARNING] ServiceManager 中的 OPCUA Server 实例为 None")
        print("这可能是因为服务是通过 web_backend/main.py 启动的")
        print("尝试通过 API 检查服务状态...")
    else:
        opcua = manager.opcua_server
        
        print(f"_running 标志: {opcua._running}")
        print(f"_server_thread: {opcua._server_thread}")
        
        if opcua._server_thread:
            print(f"  - 线程是否存活: {opcua._server_thread.is_alive()}")
            print(f"  - 线程名称: {opcua._server_thread.name}")
            print(f"  - 线程ID: {opcua._server_thread.ident}")
        
        print(f"_asyncio_loop: {opcua._asyncio_loop}")
        if opcua._asyncio_loop:
            print(f"  - 事件循环是否关闭: {opcua._asyncio_loop.is_closed()}")
            try:
                print(f"  - 事件循环是否运行: {opcua._asyncio_loop.is_running()}")
            except Exception as e:
                print(f"  - 无法检查事件循环运行状态: {e}")
        
        print(f"_update_task: {opcua._update_task}")
        if opcua._update_task:
            print(f"  - 任务是否完成: {opcua._update_task.done()}")
            print(f"  - 任务是否取消: {opcua._update_task.cancelled()}")
        
        print(f"_pubsub_task: {opcua._pubsub_task}")
        if opcua._pubsub_task:
            print(f"  - 任务是否完成: {opcua._pubsub_task.done()}")
            print(f"  - 任务是否取消: {opcua._pubsub_task.cancelled()}")
        
        print(f"server 对象: {opcua.server}")
        if opcua.server:
            print(f"  - server 类型: {type(opcua.server)}")
    
    # 通过 API 检查服务状态
    print("\n4. 通过 API 检查服务状态")
    print("-" * 60)
    
    try:
        import requests
        response = requests.get("http://localhost:8000/services/diagnostic", timeout=5)
        if response.status_code == 200:
            api_data = response.json()
            print(f"API 返回的 opcua_running: {api_data.get('opcua_running')}")
            api_services_status = api_data.get('services_status', {})
            api_opcua_status = api_services_status.get('opcua_server', {})
            print(f"\nAPI 返回的 OPCUA Server 状态:")
            print(f"  - registered: {api_opcua_status.get('registered')}")
            print(f"  - health: {api_opcua_status.get('health')}")
            print(f"  - metadata: {api_opcua_status.get('metadata')}")
            print(f"  - last_heartbeat: {api_opcua_status.get('last_heartbeat')}")
            
            # 检查所有服务列表
            all_services = api_data.get('all_services', [])
            print(f"\nAPI 返回的所有服务列表: {all_services}")
        else:
            print(f"[ERROR] API 请求失败，状态码: {response.status_code}")
    except Exception as e:
        print(f"[WARNING] 无法通过 API 检查服务状态: {e}")
        print("请确保服务正在运行（python web_backend/start_server.py）")
    
    print("=" * 60)
    print("OPCUA Server 状态检查")
    print("=" * 60)
    
    # 检查 OPCUA Server 实例
    if manager.opcua_server is None:
        print("[ERROR] OPCUA Server 实例为 None")
        return
    
    opcua = manager.opcua_server
    
    print(f"\n1. _running 标志: {opcua._running}")
    print(f"2. _server_thread: {opcua._server_thread}")
    
    if opcua._server_thread:
        print(f"   - 线程是否存活: {opcua._server_thread.is_alive()}")
        print(f"   - 线程名称: {opcua._server_thread.name}")
        print(f"   - 线程ID: {opcua._server_thread.ident}")
    
    print(f"3. _asyncio_loop: {opcua._asyncio_loop}")
    if opcua._asyncio_loop:
        print(f"   - 事件循环是否关闭: {opcua._asyncio_loop.is_closed()}")
        print(f"   - 事件循环是否运行: {opcua._asyncio_loop.is_running()}")
    
    print(f"4. _update_task: {opcua._update_task}")
    if opcua._update_task:
        print(f"   - 任务是否完成: {opcua._update_task.done()}")
        print(f"   - 任务是否取消: {opcua._update_task.cancelled()}")
    
    print(f"5. _pubsub_task: {opcua._pubsub_task}")
    if opcua._pubsub_task:
        print(f"   - 任务是否完成: {opcua._pubsub_task.done()}")
        print(f"   - 任务是否取消: {opcua._pubsub_task.cancelled()}")
    
    print(f"6. server 对象: {opcua.server}")
    if opcua.server:
        print(f"   - server 类型: {type(opcua.server)}")
    
    # 检查诊断信息中的运行状态
    print("\n" + "=" * 60)
    print("ServiceManager 诊断信息")
    print("=" * 60)
    
    diagnostic = manager.get_diagnostic_info()
    print(f"opcua_running: {diagnostic.get('opcua_running')}")
    
    services_status = diagnostic.get('services_status', {})
    opcua_status = services_status.get('opcua_server', {})
    print(f"\nOPCUA Server 服务状态:")
    print(f"  - registered: {opcua_status.get('registered')}")
    print(f"  - health: {opcua_status.get('health')}")
    print(f"  - last_heartbeat: {opcua_status.get('last_heartbeat')}")
    
    # 检查 Redis 中的服务注册信息
    print("\n" + "=" * 60)
    print("Redis 中的服务注册信息")
    print("=" * 60)
    
    try:
        redis_client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
        )
        
        # 检查服务注册表
        registry_key = "service_manager:services"
        all_services = redis_client.hkeys(registry_key)
        print(f"所有已注册的服务: {all_services}")
        
        if "opcua_server" in all_services:
            service_info_json = redis_client.hget(registry_key, "opcua_server")
            import json
            service_info = json.loads(service_info_json)
            print(f"\nOPCUA Server 注册信息:")
            print(f"  - name: {service_info.get('name')}")
            print(f"  - metadata: {service_info.get('metadata')}")
            print(f"  - registered_at: {service_info.get('registered_at')}")
            print(f"  - last_heartbeat: {service_info.get('last_heartbeat')}")
        
        # 检查健康状态
        health_key = "service_manager:health:opcua_server"
        health_info_json = redis_client.get(health_key)
        if health_info_json:
            health_info = json.loads(health_info_json)
            print(f"\nOPCUA Server 健康状态:")
            print(f"  - status: {health_info.get('status')}")
            print(f"  - timestamp: {health_info.get('timestamp')}")
        else:
            print("\n[ERROR] Redis 中没有找到 OPCUA Server 的健康状态")
            
    except Exception as e:
        print(f"[ERROR] 检查 Redis 时出错: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_opcua_status()

