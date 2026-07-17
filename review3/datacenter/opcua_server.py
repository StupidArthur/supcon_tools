"""
OPCUA Server 模块（独立版）

纯内存驱动的 OPCUA Server，从 shared_realtime_data 读取数据并更新节点。
支持外部写值，通过 command_queue 传递命令给 Engine。
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional

from asyncua import Server, ua

from components.utils.logger import get_logger

_base_logger = get_logger()
logger = logging.getLogger("data_next.opcua_server")
if not logger.handlers:
    for h in _base_logger.handlers:
        logger.addHandler(h)
logger.setLevel(_base_logger.level)
logger.propagate = False
logging.getLogger("asyncua").setLevel(logging.ERROR)


@dataclass
class OPCUAServerConfig:
    """
    OPCUA Server 配置

    Attributes:
        server_url: OPCUA Server 地址，默认 opc.tcp://0.0.0.0:18951
        update_cycle: 更新周期（秒），默认 0.1 秒
        enable_write: 是否启用写值功能（默认 True）
    """
    server_url: str = "opc.tcp://0.0.0.0:18951"
    update_cycle: float = 0.1
    enable_write: bool = True


class StandaloneOpcuaServer:
    """
    独立版 OPCUA Server（纯内存驱动）

    功能：
    - 从 shared_realtime_data 读取数据更新节点
    - 监听 command_queue 接收外部写值命令
    - 动态创建节点（使用位号名作为节点标识）
    - 支持写值功能，通过 command_queue 发送命令给 Engine
    """

    def __init__(
        self,
        config: OPCUAServerConfig,
        shared_data: Dict[str, float],
        cmd_queue: queue.Queue,
    ) -> None:
        """
        初始化 OPCUA Server

        Args:
            config: OPCUA Server 配置
            shared_data: 共享内存数据字典（引擎计算完每个周期后更新）
            cmd_queue: 命令队列（用于向引擎发送写值命令）
        """
        self.config = config
        self._shared_data = shared_data
        self._cmd_queue = cmd_queue

        # OPCUA Server
        self.server: Optional[Server] = None
        self.namespace_idx: Optional[int] = None

        # 存储节点映射：位号名（param_name） -> 节点对象
        self.node_map: Dict[str, Any] = {}

        # 存储节点类型映射：位号名 -> VariantType
        self.node_type_map: Dict[str, ua.VariantType] = {}

        # 运行控制
        self._running = False
        self._is_updating = False  # 防止内部更新触发 setter
        self._asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_thread: Optional[threading.Thread] = None
        # server 就绪信号（避免客户端在 server.start() 后立刻 connect 时端口还没起来）
        self._ready_event = threading.Event()

        logger.info(
            "StandaloneOpcuaServer initialized: server_url=%s, update_cycle=%.2f, write_enabled=%s",
            config.server_url,
            config.update_cycle,
            config.enable_write,
        )

    async def _init_server(self) -> None:
        """初始化 OPCUA Server"""
        self.server = Server()
        await self.server.init()

        self.server.set_endpoint(self.config.server_url)
        self.server.set_server_name("Data Factory OPCUA Server")

        uri = "http://data_factory.opcua"
        self.namespace_idx = await self.server.register_namespace(uri)
        logger.info(f"OPCUA Server namespace registered: {uri} (idx={self.namespace_idx})")

        objects = self.server.get_objects_node()

        node_id = ua.NodeId("DataFactory", self.namespace_idx)
        self._root_folder = await objects.add_folder(node_id, "DataFactory")

        logger.info("OPCUA Server initialized")

    async def _create_node(self, param_name: str, initial_value: float = 0.0) -> None:
        """创建 OPCUA 节点"""
        if param_name in self.node_map:
            return

        try:
            node_id = ua.NodeId(param_name, self.namespace_idx)
            var_node = self.server.get_node(node_id)
            await var_node.read_browse_name()
            self.node_map[param_name] = var_node
            self.node_type_map[param_name] = ua.VariantType.Double
            return
        except Exception:
            pass

        try:
            node_id = ua.NodeId(param_name, self.namespace_idx)
            var_node = await self._root_folder.add_variable(
                node_id,
                param_name,
                ua.Variant(initial_value, ua.VariantType.Double)
            )
            if hasattr(var_node, "set_display_name"):
                await var_node.set_display_name(ua.LocalizedText(param_name))

            if self.config.enable_write:
                await var_node.set_writable(True)
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
                try:
                    node_id = ua.NodeId(param_name, self.namespace_idx)
                    var_node = self.server.get_node(node_id)
                    if self.config.enable_write:
                        await var_node.set_writable(True)
                        self._bind_write_setter(node_id, param_name)
                    self.node_map[param_name] = var_node
                    self.node_type_map[param_name] = ua.VariantType.Double
                except Exception as ex:
                    logger.debug(f"reuse existing node failed for {param_name}: {ex}")
            else:
                logger.error(f"Failed to create node {param_name}: {e}")

    def _bind_write_setter(self, node_id: ua.NodeId, param_name: str) -> None:
        """绑定 OPCUA 写值 setter"""
        if not self.server:
            return

        def _setter(node_data: Any, attr: ua.AttributeIds, value: ua.DataValue) -> None:
            try:
                node_data.attributes[attr].value = value
                node_data.attributes[attr].value_callback = None

                # 忽略内部更新导致的 setter 调用
                if self._is_updating:
                    return

                if value is None or value.Value is None:
                    return

                python_value = value.Value.Value
                logger.info("OPCUA external write captured: %s=%s", param_name, python_value)

                # 将写值命令放入队列
                self._cmd_queue.put({
                    "tag": param_name,
                    "value": python_value,
                })
            except Exception as ex:
                logger.error("OPCUA write setter error for %s: %s", param_name, ex, exc_info=True)

        self.server.set_attribute_value_setter(node_id, _setter, ua.AttributeIds.Value)

    async def _update_nodes(self, params: Dict[str, float]) -> None:
        """更新 OPCUA 节点值"""
        self._is_updating = True
        try:
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

                    variant_type = self.node_type_map.get(param_name, ua.VariantType.Double)
                    update_tasks.append(
                        node.write_value(ua.Variant(float(param_value), variant_type))
                    )

            if update_tasks:
                try:
                    await asyncio.gather(*update_tasks, return_exceptions=True)
                except Exception as e:
                    logger.error(f"Error in batch update: {e}")
        finally:
            self._is_updating = False

    async def _poll_memory_data(self) -> None:
        """轮询共享内存数据并更新 OPCUA 节点"""
        while self._running:
            try:
                # 从共享内存读取数据
                params = dict(self._shared_data)

                if params:
                    await self._update_nodes(params)

                await asyncio.sleep(self.config.update_cycle)
            except Exception as e:
                logger.error(f"Error in poll memory data: {e}", exc_info=True)
                await asyncio.sleep(self.config.update_cycle)

    async def _run_server(self) -> None:
        """运行 OPCUA Server"""
        try:
            await self.server.start()
            logger.info(f"OPCUA Server started at {self.config.server_url}")
            # 标记 server 已就绪（监听端口已打开、namespace 已注册），调用方可同步等待
            self._ready_event.set()

            endpoints = await self.server.get_endpoints()
            logger.info("Available endpoints:")
            for endpoint in endpoints:
                logger.info(f"  - {endpoint.EndpointUrl}")
                logger.info(f"    Security Policy: {endpoint.SecurityPolicyUri}")
                logger.info(f"    Security Mode: {endpoint.SecurityMode}")

            # 启动内存轮询任务
            poll_task = asyncio.create_task(self._poll_memory_data())

            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Server tasks cancelled")
            finally:
                if not poll_task.done():
                    poll_task.cancel()
                    try:
                        await poll_task
                    except asyncio.CancelledError:
                        pass
        except Exception as e:
            logger.error(f"Error running OPCUA Server: {e}", exc_info=True)
            raise
        finally:
            if self.server:
                await self.server.stop()
                logger.info("OPCUA Server stopped")

    def start(self) -> None:
        """启动 OPCUA Server"""
        if self._running:
            logger.warning("OPCUA Server is already running")
            return

        self._running = True

        def run_in_thread():
            self._asyncio_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._asyncio_loop)

            try:
                self._asyncio_loop.run_until_complete(self._init_server())
                self._asyncio_loop.run_until_complete(self._run_server())
            except Exception as e:
                logger.error(f"Error in OPCUA Server thread: {e}", exc_info=True)
                self._running = False
            finally:
                try:
                    if self._asyncio_loop and not self._asyncio_loop.is_closed():
                        self._asyncio_loop.close()
                except Exception:
                    pass
                self._running = False

        self._server_thread = threading.Thread(target=run_in_thread, daemon=True)
        self._server_thread.start()

        logger.info("OPCUA Server started in background thread")

    def stop(self) -> None:
        """停止 OPCUA Server"""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping OPCUA Server...")

    def close(self) -> None:
        """关闭 OPCUA Server"""
        self.stop()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """
        同步等待 server 启动就绪。

        在 ``start()`` 返回后调用，会阻塞直到 ``await self.server.start()`` 完成、
        监听端口已打开，或超时返回 False。

        Args:
            timeout: 最长等待秒数。

        Returns:
            True 表示在 timeout 内就绪；False 表示超时或初始化失败。
        """
        return self._ready_event.wait(timeout)

    def join(self, timeout: Optional[float] = None) -> None:
        """
        阻塞直到 server 后台线程结束。

        用于主线程防止进程退出；Ctrl+C 后建议配合 ``stop()`` 调用。
        """
        if self._server_thread is not None:
            self._server_thread.join(timeout)
