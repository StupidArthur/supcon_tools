"""
OPCUA Server 模块

独立启动的 OPCUA Server，从 Redis 读取数据并更新节点。
节点的 name、display_name、browse_name、node_id 都使用位号名（param_name）。
支持写值功能，通过消息总线发送命令给 Engine。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

import redis
from asyncua import Server, ua

from components.utils.logger import get_logger

# 可选导入消息总线
try:
    from components.message_bus import MessageBus, BusConfig, MessageClient, ServiceRegistry
    MESSAGE_BUS_AVAILABLE = True
except ImportError:
    MESSAGE_BUS_AVAILABLE = False
    MessageBus = None
    BusConfig = None
    MessageClient = None
    ServiceRegistry = None


_base_logger = get_logger()
# OPCUA 独立子 logger：沿用文件 handler，但禁止向根 logger 传播，避免控制台刷屏
logger = logging.getLogger("data_next.opcua_server")
if not logger.handlers:
    for h in _base_logger.handlers:
        logger.addHandler(h)
logger.setLevel(_base_logger.level)
logger.propagate = False
# 避免 asyncua 在节点重复创建场景下向控制台输出过多告警
logging.getLogger("asyncua").setLevel(logging.ERROR)


@dataclass
class OPCUAServerConfig:
    """
    OPCUA Server 配置
    
    Attributes:
        server_url: OPCUA Server 地址，默认 opc.tcp://0.0.0.0:18951
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码（可选）
        pubsub_channel: Pub/Sub 频道名称，用于接收数据更新通知
        update_cycle: 更新周期（秒），默认 1.0 秒
        bus_config: 消息总线配置（如果为 None，则使用默认配置）
        enable_write: 是否启用写值功能（默认 True）
    """
    server_url: str = "opc.tcp://0.0.0.0:18951"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    pubsub_channel: str = "data_factory"
    update_cycle: float = 1.0  # 降低更新频率到1秒，减少性能开销
    bus_config: Optional[Any] = None  # BusConfig 类型
    enable_write: bool = True  # 是否启用写值功能


class OPCUAServer:
    """
    OPCUA Server
    
    功能：
    - 从 Redis 读取数据（data_factory:v2:current）
    - 监听 Pub/Sub 频道接收更新通知
    - 动态创建节点（使用位号名作为节点标识）
    - 更新节点值
    - 支持写值功能，通过消息总线发送命令给 Engine
    """
    
    # Redis 键前缀
    REDIS_KEY_PREFIX = "data_factory"
    
    def __init__(self, config: OPCUAServerConfig):
        """
        初始化 OPCUA Server
        
        Args:
            config: OPCUA Server 配置
        """
        self.config = config
        
        # 初始化 Redis 连接
        self.redis_client = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password,
            decode_responses=True,
        )
        
        # 测试 Redis 连接
        try:
            self.redis_client.ping()
            logger.info("Redis connection established in OPCUA Server")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
        # 初始化消息总线（用于发送写值命令和服务注册）
        self._bus: Optional[Any] = None
        self._client: Optional[Any] = None
        self._service_registry: Optional[Any] = None
        if MESSAGE_BUS_AVAILABLE:
            self._init_message_bus()
        
        # OPCUA Server
        self.server: Optional[Server] = None
        self.namespace_idx: Optional[int] = None
        
        # 存储节点映射：位号名（param_name） -> 节点对象
        self.node_map: Dict[str, Any] = {}
        
        # 存储节点类型映射：位号名 -> VariantType
        self.node_type_map: Dict[str, ua.VariantType] = {}
        # 内部写入保护：避免 server 自己 write_value 被当成外部 UA 写值转发
        self._internal_writes: set[str] = set()
        
        # 运行控制
        self._running = False
        self._asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_task: Optional[asyncio.Task] = None
        self._update_task: Optional[asyncio.Task] = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._server_thread: Optional[threading.Thread] = None  # 保存服务器线程引用
        
        # 诊断提供者（可选）
        self._diagnostic_provider: Optional[Any] = None
        
        logger.info(
            "OPCUA Server initialized: server_url=%s, redis=%s:%d/%d, channel=%s, write_enabled=%s",
            config.server_url,
            config.redis_host,
            config.redis_port,
            config.redis_db,
            config.pubsub_channel,
            config.enable_write and self._client is not None,
        )
    
    def _init_diagnostics(self) -> None:
        """初始化诊断提供者"""
        try:
            from datacenter.diagnostics import OPCUADiagnosticProvider
            
            self._diagnostic_provider = OPCUADiagnosticProvider(self, self.redis_client)
            logger.info("诊断提供者已初始化")
        except ImportError:
            logger.debug("诊断模块不可用，跳过诊断初始化")
        except Exception as e:
            logger.warning(f"诊断提供者初始化失败: {e}", exc_info=True)
    
    def _init_message_bus(self) -> None:
        """初始化消息总线"""
        if not MESSAGE_BUS_AVAILABLE:
            logger.warning("消息总线不可用，写值功能将不可用")
            return
        
        try:
            if self.config.bus_config:
                bus_config = self.config.bus_config
            else:
                bus_config = BusConfig(
                    redis_host=self.config.redis_host,
                    redis_port=self.config.redis_port,
                    redis_db=self.config.redis_db,
                    redis_password=self.config.redis_password,
                    key_prefix="service_manager"  # 使用与ServiceManager相同的key_prefix
                )
            
            self._bus = MessageBus(bus_config)
            self._client = MessageClient(self._bus, "opcua_server")
            self._service_registry = ServiceRegistry(self._bus)
            logger.info("消息总线初始化成功，写值功能可用")
        except Exception as e:
            logger.error(f"消息总线初始化失败: {e}", exc_info=True)
            self._bus = None
            self._client = None
    
    async def _init_server(self) -> None:
        """初始化 OPCUA Server"""
        self.server = Server()
        await self.server.init()
        
        # 设置端点（允许匿名连接）
        # asyncua 默认会创建一个端点，但我们需要确保配置正确
        # 设置端点URL
        self.server.set_endpoint(self.config.server_url)
        
        # 设置服务器名称
        self.server.set_server_name("Data Factory OPCUA Server")
        
        # 注意：asyncua 默认允许 NoSecurity（无安全策略）连接
        # 这允许标准客户端匿名连接，无需证书
        # 在生产环境中应该配置带安全策略的连接
        
        # 注册命名空间
        uri = "http://data_factory.opcua"
        self.namespace_idx = await self.server.register_namespace(uri)
        logger.info(f"OPCUA Server namespace registered: {uri} (idx={self.namespace_idx})")
        
        # 获取 Objects 文件夹
        objects = self.server.get_objects_node()
        
        # 创建根文件夹
        # add_folder(nodeid, bname) - nodeid 使用命名空间索引和字符串ID
        node_id = ua.NodeId("DataFactory", self.namespace_idx)
        root_folder = await objects.add_folder(
            node_id,
            "DataFactory"
        )
        
        # 存储根文件夹（用于后续创建节点）
        self._root_folder = root_folder
        
        logger.info("OPCUA Server initialized")
    
    async def _create_node(self, param_name: str, initial_value: float = 0.0) -> None:
        """
        创建 OPCUA 节点（使用位号名）
        
        Args:
            param_name: 位号名（如 "tank1.level"）
            initial_value: 初始值
        """
        # 检查节点是否已在映射中
        if param_name in self.node_map:
            return
        
        # 先按 NodeId 探测是否已存在（比 get_child 更稳，避免误判后触发重复 add）
        try:
            node_id = ua.NodeId(param_name, self.namespace_idx)
            var_node = self.server.get_node(node_id)  # type: ignore[union-attr]
            # 如果节点不存在，读取 BrowseName 会抛异常
            await var_node.read_browse_name()
            if self.config.enable_write and self._client is not None:
                try:
                    await var_node.set_writable(True)
                    self._bind_write_setter(node_id, param_name)
                except Exception as ex:
                    logger.debug(f"bind write callback skipped for existing node {param_name}: {ex}")
            self.node_map[param_name] = var_node
            self.node_type_map[param_name] = ua.VariantType.Double
            return
        except Exception:
            # 节点不存在，继续创建
            pass
        
        # 创建新节点
        try:
            node_id = ua.NodeId(param_name, self.namespace_idx)
            var_node = await self._root_folder.add_variable(
                node_id,
                param_name,
                ua.Variant(initial_value, ua.VariantType.Double)
            )
            if hasattr(var_node, "set_display_name"):
                await var_node.set_display_name(ua.LocalizedText(param_name))
            # 如果启用写值功能，设置为可写
            await var_node.set_writable(self.config.enable_write and self._client is not None)
            
            # 如果可写，注册写值回调
            if self.config.enable_write and self._client is not None:
                self._bind_write_setter(node_id, param_name)
            
            self.node_map[param_name] = var_node
            self.node_type_map[param_name] = ua.VariantType.Double
        except Exception as e:
            error_msg = str(e).lower()
            if (
                "already exists" in error_msg
                or "already used" in error_msg
                or "badnodeidexists" in error_msg
                or "duplicate" in error_msg
            ):
                # 节点已存在，再次尝试获取
                try:
                    node_id = ua.NodeId(param_name, self.namespace_idx)
                    var_node = self.server.get_node(node_id)  # type: ignore[union-attr]
                    if self.config.enable_write and self._client is not None:
                        try:
                            await var_node.set_writable(True)
                            self._bind_write_setter(node_id, param_name)
                        except Exception as ex:
                            logger.debug(f"bind write callback skipped for reused node {param_name}: {ex}")
                    self.node_map[param_name] = var_node
                    self.node_type_map[param_name] = ua.VariantType.Double
                except Exception as ex:
                    logger.debug(f"reuse existing node failed for {param_name}: {ex}")
            else:
                logger.error(f"Failed to create node {param_name}: {e}")

    def _bind_write_setter(self, node_id: ua.NodeId, param_name: str) -> None:
        """
        绑定 OPCUA 写值 setter（兼容 asyncua 新版本，替代 set_write_value 回调）。
        """
        if not self.server or not self._client:
            return

        def _setter(node_data: Any, attr: ua.AttributeIds, value: ua.DataValue) -> None:
            try:
                # 先写入 OPCUA 地址空间值，保证客户端写后读回一致
                node_data.attributes[attr].value = value
                node_data.attributes[attr].value_callback = None
                # server 内部刷新值不转发，避免回写风暴
                if param_name in self._internal_writes:
                    logger.debug("OPCUA setter internal write ignored: %s", param_name)
                    return

                if value is None or value.Value is None:
                    return
                python_value = value.Value.Value
                logger.info("OPCUA external write captured: %s=%s", param_name, python_value)
                target_service = "engine"
                if "." in param_name:
                    namespace = param_name.split(".", 1)[0]
                    target_service = f"engine.{namespace}"
                # 目标引擎服务不存在时回退到兼容服务名
                if self._client.discover(target_service) is None:
                    target_service = "engine"
                result = self._client.call(
                    target_service,
                    "opcua_write_value",
                    {"param_name": param_name, "value": python_value},
                    timeout=5.0,
                )
                if not (result and result.get("success")):
                    logger.error(
                        "OPCUA write forward failed: %s=%s, result=%s",
                        param_name,
                        python_value,
                        result,
                    )
            except Exception as ex:
                logger.error("OPCUA write setter error for %s: %s", param_name, ex, exc_info=True)

        self.server.set_attribute_value_setter(node_id, _setter, ua.AttributeIds.Value)
    
    async def _update_nodes(self, params: Dict[str, Any]) -> None:
        """
        更新 OPCUA 节点值（批量更新）
        
        Args:
            params: 参数字典，key 为位号名，value 为参数值
        """
        # 批量更新节点值（缺失节点先创建，避免“已有值但节点未入映射”导致不刷新）
        update_keys = []
        update_tasks = []
        for param_name, param_value in params.items():
            node = self.node_map.get(param_name)
            if isinstance(param_value, (int, float)):
                if node is None:
                    try:
                        await self._create_node(param_name, float(param_value))
                    except Exception as e:
                        logger.debug(f"create node before write failed: {param_name}, err={e}")
                    node = self.node_map.get(param_name)
                if node is None:
                    continue

                redis_value = float(param_value)
                variant_type = self.node_type_map.get(param_name, ua.VariantType.Double)
                self._internal_writes.add(param_name)
                try:
                    update_tasks.append(node.write_value(ua.Variant(redis_value, variant_type)))
                    update_keys.append(param_name)
                except Exception:
                    self._internal_writes.discard(param_name)
        
        # 并发更新所有节点值
        if update_tasks:
            try:
                results = await asyncio.gather(*update_tasks, return_exceptions=True)
                # 仅在“节点确实失效”时移除缓存，避免健康节点被误删导致 node_count 清零
                failed_keys = []
                for idx, result in enumerate(results):
                    if isinstance(result, Exception):
                        err = str(result)
                        if "BadNodeIdUnknown" in err or "BadSessionIdInvalid" in err:
                            failed_keys.append(update_keys[idx])
                    # 无论成功失败都清理内部写保护
                    self._internal_writes.discard(update_keys[idx])
                for k in failed_keys:
                    self.node_map.pop(k, None)
                    self.node_type_map.pop(k, None)
                if failed_keys:
                    logger.debug("OPCUA write failed for %d nodes, evicted from cache", len(failed_keys))
            except Exception as e:
                logger.error(f"Error in batch update: {e}")
    
    async def _on_write_value(self, node: Any, value: Any, data_type: Any) -> ua.DataValue:
        """
        OPCUA 写值回调处理
        
        Args:
            node: 节点对象
            value: 写入的值（DataValue 类型）
            data_type: 数据类型
        
        Returns:
            DataValue: 返回处理后的值（允许修改）
        """
        try:
            # 获取参数名（从节点的 nodeid.Identifier，因为创建时使用的是 param_name）
            param_name = str(node.nodeid.Identifier)
            
            # 验证参数名是否在映射中（可选，用于调试）
            if param_name not in self.node_map:
                logger.warning(f"Write value for unknown param: {param_name}")
            
            # 转换值为 Python 类型
            if isinstance(value, ua.DataValue):
                python_value = value.Value.Value if value.Value else None
            elif isinstance(value, ua.Variant):
                python_value = value.Value
            else:
                python_value = value
            
            # 通过消息总线发送写值命令给 Engine（同步调用，在后台线程执行）
            if self._client:
                try:
                    # 在后台线程中执行同步调用
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: self._client.call(
                            "engine",
                            "opcua_write_value",
                            {"param_name": param_name, "value": python_value},
                            timeout=5.0
                        )
                    )
                    if result and result.get("success"):
                        logger.info(f"OPCUA write value sent: {param_name} = {python_value}")
                    else:
                        logger.error(f"OPCUA write value failed: {param_name} = {python_value}, error={result.get('error')}")
                except Exception as e:
                    logger.error(f"Failed to send OPCUA write value command: {e}", exc_info=True)
            else:
                logger.warning(f"Message bus not available, cannot send write value: {param_name} = {python_value}")
            
            # 返回原始值（允许写入）
            return value
        except Exception as e:
            logger.error(f"Error in write value callback: {e}", exc_info=True)
            # 返回原始值，允许写入
            return value
    
    async def _update_loop(self) -> None:
        """更新循环（从 Redis 读取数据并更新 OPCUA 节点）"""
        update_count = 0
        no_data_count = 0
        
        # 诊断更新间隔（秒）
        diagnostic_interval = 1.0
        last_diagnostic_update = 0.0
        
        while self._running:
            try:
                cycle_start_time = time.time()
                
                # 从 Redis 读取当前数据 (V2 Hash 模式)
                redis_key = f"{self.REDIS_KEY_PREFIX}:v2:current"
                fields_data = self.redis_client.hgetall(redis_key)
                
                if fields_data:
                    try:
                        # 解析 V2 格式：{tag: {"v": value, "t": time, "e": engine}}
                        params = {}
                        for tag, val_json in fields_data.items():
                            try:
                                meta = json.loads(val_json)
                                params[tag] = meta.get("v", 0.0)
                            except:
                                continue
                        
                        if params:
                            # 更新 OPCUA 节点
                            await self._update_nodes(params)
                            update_count += 1
                            
                            # 更新诊断提供者的更新计数
                            if self._diagnostic_provider:
                                self._diagnostic_provider.increment_update_count()
                            
                            # 每1000次更新输出一次统计信息
                            if update_count % 1000 == 0:
                                logger.info(
                                    f"Update loop (V2): updated {update_count} times, "
                                    f"total nodes: {len(self.node_map)}"
                                )
                    except Exception as e:
                        logger.error(f"Failed to parse V2 data from Redis: {e}")
                else:
                    no_data_count += 1
                    if no_data_count % 1000 == 0:
                        logger.warning(f"No V2 data in Redis (key: {redis_key})")
                
                # 计算执行时间
                cycle_time = time.time() - cycle_start_time
                
                # 定期更新诊断信息
                current_time = time.time()
                if current_time - last_diagnostic_update >= diagnostic_interval:
                    if self._diagnostic_provider:
                        try:
                            self._diagnostic_provider.push_diagnostics()
                            last_diagnostic_update = current_time
                        except Exception as e:
                            logger.debug(f"Failed to update diagnostics: {e}")
                
                # 睡眠到下一个周期
                sleep_time = self.config.update_cycle - cycle_time
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    # 只在第一次超时时输出警告
                    if update_count == 1:
                        logger.warning(
                            f"Update cycle time ({cycle_time:.4f}s) exceeds cycle time ({self.config.update_cycle}s)"
                        )
            except Exception as e:
                logger.error(f"Error in update loop: {e}", exc_info=True)
                await asyncio.sleep(self.config.update_cycle)
    
    async def _pubsub_loop(self) -> None:
        """Pub/Sub 监听循环（接收数据更新通知）"""
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe(self.config.pubsub_channel)
        
        logger.info(f"Subscribed to Redis Pub/Sub channel: {self.config.pubsub_channel}")
        
        notification_count = 0
        
        try:
            while self._running:
                try:
                    # 接收消息（非阻塞）
                    message = pubsub.get_message(timeout=0.1)
                    
                    if message and message["type"] == "message":
                        notification_count += 1
                        
                        # 统一读取 V2 路径（v1 已下线）
                        redis_key = f"{self.REDIS_KEY_PREFIX}:v2:current"
                        fields_data = self.redis_client.hgetall(redis_key)
                        if fields_data:
                            params = {}
                            for tag, val_json in fields_data.items():
                                try:
                                    meta = json.loads(val_json)
                                    params[tag] = meta.get("v", 0.0)
                                except Exception:
                                    continue
                            await self._update_nodes(params)

                        # 每1000次通知输出一次日志
                        if notification_count % 1000 == 0:
                            logger.debug(f"Received {notification_count} Pub/Sub notifications")
                    
                    await asyncio.sleep(0.01)  # 短暂休眠，避免 CPU 占用过高
                except Exception as e:
                    logger.error(f"Error in pubsub loop: {e}", exc_info=True)
                    await asyncio.sleep(0.1)
        finally:
            pubsub.close()
            logger.info("Pub/Sub connection closed")
    
    async def _run_server(self) -> None:
        """运行 OPCUA Server"""
        try:
            # 启动服务器
            await self.server.start()
            logger.info(f"OPCUA Server started at {self.config.server_url}")
            
            # 输出端点信息，方便客户端连接
            endpoints = await self.server.get_endpoints()
            logger.info("Available endpoints:")
            for endpoint in endpoints:
                logger.info(f"  - {endpoint.EndpointUrl}")
                logger.info(f"    Security Policy: {endpoint.SecurityPolicyUri}")
                logger.info(f"    Security Mode: {endpoint.SecurityMode}")
            
            # 启动更新任务
            self._update_task = asyncio.create_task(self._update_loop())
            
            # 启动 Pub/Sub 任务
            self._pubsub_task = asyncio.create_task(self._pubsub_loop())
            
            # 定期更新服务心跳和健康状态
            async def heartbeat_loop():
                while self._running:
                    await asyncio.sleep(5)  # 每5秒更新一次
                    if self._service_registry:
                        try:
                            self._service_registry.update_heartbeat("opcua_server")
                            self._service_registry.update_health("opcua_server", "healthy")
                        except Exception:
                            pass
            
            heartbeat_task = asyncio.create_task(heartbeat_loop())
            
            # 等待服务器运行
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Server tasks cancelled")
            finally:
                # 取消心跳任务
                if not heartbeat_task.done():
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
        except Exception as e:
            logger.error(f"Error running OPCUA Server: {e}", exc_info=True)
            raise
        finally:
            # 取消任务
            if self._update_task and not self._update_task.done():
                self._update_task.cancel()
                try:
                    await self._update_task
                except asyncio.CancelledError:
                    pass
            
            if self._pubsub_task and not self._pubsub_task.done():
                self._pubsub_task.cancel()
                try:
                    await self._pubsub_task
                except asyncio.CancelledError:
                    pass
            
            # 停止服务器
            if self.server:
                await self.server.stop()
                logger.info("OPCUA Server stopped")
    
    def start(self) -> None:
        """启动 OPCUA Server（在新的事件循环中运行）"""
        if self._running:
            logger.warning("OPCUA Server is already running")
            return
        
        # 注册服务（如果使用消息总线）
        if self._service_registry:
            try:
                self._service_registry.register(
                    "opcua_server",
                    metadata={
                        "version": "1.0.0",
                        "description": "OPCUA Server",
                        "capabilities": ["opcua_read", "opcua_write"] if self.config.enable_write else ["opcua_read"],
                        "status": "starting",
                        "server_url": self.config.server_url,
                        "write_enabled": self.config.enable_write and self._client is not None,
                    }
                )
                logger.info("服务已注册: opcua_server")
            except Exception as e:
                logger.warning(f"Failed to register service: {e}")
        
        # 初始化诊断提供者
        self._init_diagnostics()
        
        self._running = True
        
        # 创建新的事件循环（在新线程中）
        def run_in_thread():
            self._asyncio_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._asyncio_loop)
            
            try:
                # 初始化服务器
                self._asyncio_loop.run_until_complete(self._init_server())
                
                # 更新服务状态为运行中
                if self._service_registry:
                    try:
                        self._service_registry.update_health("opcua_server", "healthy")
                    except Exception:
                        pass
                
                # 运行服务器
                self._asyncio_loop.run_until_complete(self._run_server())
            except Exception as e:
                logger.error(f"Error in OPCUA Server thread: {e}", exc_info=True)
                self._running = False  # 发生异常时，设置运行标志为False
                # 更新服务状态为不健康
                if self._service_registry:
                    try:
                        self._service_registry.update_health("opcua_server", "unhealthy")
                    except Exception:
                        pass
            finally:
                try:
                    if self._asyncio_loop and not self._asyncio_loop.is_closed():
                        self._asyncio_loop.close()
                except Exception:
                    pass
                self._running = False  # 确保在退出时设置运行标志为False
        
        # 启动线程
        self._server_thread = threading.Thread(target=run_in_thread, daemon=True)
        self._server_thread.start()
        
        logger.info("OPCUA Server started in background thread")
    
    def stop(self) -> None:
        """停止 OPCUA Server"""
        if not self._running:
            logger.warning("OPCUA Server is not running")
            return
        
        # 更新服务状态为停止中
        if self._service_registry:
            try:
                self._service_registry.update_health("opcua_server", "stopping")
            except Exception:
                pass
        
        self._running = False
        
        # 停止服务器（通过设置标志，让事件循环自然退出）
        logger.info("Stopping OPCUA Server...")
    
    def close(self) -> None:
        """关闭 OPCUA Server 和连接"""
        self.stop()
        
        # 注销服务
        if self._service_registry:
            try:
                self._service_registry.unregister("opcua_server")
            except Exception:
                pass
        
        # 关闭消息总线
        try:
            if self._bus:
                self._bus.close()
                logger.info("消息总线连接已关闭")
        except Exception as e:
            logger.error(f"Failed to close message bus: {e}", exc_info=True)
        
        # 关闭 Redis 连接
        if self.redis_client:
            self.redis_client.close()
            logger.info("Redis connection closed")

