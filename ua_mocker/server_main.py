# -*- coding: utf-8 -*-
"""
OPC UA Mock Server 主逻辑：根据组态创建命名空间与变量节点，
所有变量挂在 Objects 下的容器对象「mocker」之下（浏览路径：Objects → mocker → 变量）。
对 change=true 的节点按 cycle 周期更新值；可写节点由客户端写后持久化（由 asyncua 负责）。
控制台仅输出：开始构建节点树、构建完成、服务启动成功+端口、节点数量、designed by yzc，以及客户端写值消息。
"""

import asyncio
import logging
from typing import Any

from asyncua import Server, ua
from asyncua.common.callback import CallbackType

from change_engines import next_value
from config_loader import load_config
from type_mapping import (
    coerce_to_type,
    get_variant_type_and_default,
)

logger = logging.getLogger(__name__)

# 控制台仅打印的固定信息与署名
CONSOLE_BUILD_START = "开始构建节点树"
CONSOLE_BUILD_DONE = "构建完成"
CONSOLE_SERVER_START = "服务启动成功"
CONSOLE_DESIGNED_BY = "designed by yzc"

# 变量节点父对象：Objects 下的对象 BrowseName
CONTAINER_OBJECT_NAME = "mocker"


def _node_id_string(name_prefix: str, index: int) -> str:
    """组态 name + 下标拼接为 NodeId 的字符串标识。"""
    return f"{name_prefix}{index}"


def _initial_value(node_cfg: dict, variant_type: ua.VariantType, default_py: Any) -> Any:
    """取节点初始值：change=false 用 default（并做类型转换），change=true 用引擎的起始值。"""
    if node_cfg.get("change") is True:
        return next_value(variant_type, None)
    raw = node_cfg.get("default", default_py)
    return coerce_to_type(raw, variant_type)


async def run_server(config_path: str) -> None:
    """
    加载组态并启动 OPC UA 服务器，阻塞直到被中断。

    :param config_path: 组态文件路径（YAML）
    """
    cfg = load_config(config_path)
    server = Server()
    await server.init()

    host = cfg["server"]
    port = int(cfg["port"])
    cycle_ms = int(cfg["cycle"])
    namespace_index = int(cfg["namespace_index"])

    endpoint = f"opc.tcp://{host}:{port}/ua_mocker/"
    server.set_endpoint(endpoint)
    logger.info("OPC UA 端点: %s", endpoint)

    # 使用组态中的 namespace_index 创建节点，使客户端看到的 ns 与配置文件一致
    ns_idx = namespace_index
    logger.info("命名空间索引(与配置一致): %s", ns_idx)

    objects = server.nodes.objects
    mocker_root = await objects.add_object(
        ns_idx,
        CONTAINER_OBJECT_NAME,
        ua.ObjectIds.BaseObjectType,
    )
    logger.info("变量父节点: Objects/%s (ns=%s)", CONTAINER_OBJECT_NAME, ns_idx)

    # 记录 change=true 的节点：(node, variant_type) 用于周期更新
    change_nodes: list[tuple[Any, ua.VariantType]] = []
    total_node_count = 0

    print(CONSOLE_BUILD_START)
    for node_cfg in cfg["nodes"]:
        name_prefix = node_cfg["name"]
        type_name = node_cfg["type"]
        count = int(node_cfg["count"])
        change = node_cfg["change"] is True
        writable = node_cfg["writable"] is True

        variant_type, default_py = get_variant_type_and_default(type_name)

        for i in range(1, count + 1):
            total_node_count += 1
            node_id_str = _node_id_string(name_prefix, i)
            node_id = ua.NodeId(node_id_str, ns_idx)
            qname = ua.QualifiedName(node_id_str, ns_idx)
            initial = _initial_value(node_cfg, variant_type, default_py)

            try:
                n = await mocker_root.add_variable(node_id, qname, initial)
            except Exception as e:
                logger.warning("添加变量 %s 失败: %s，尝试使用自动 NodeId", node_id_str, e)
                n = await mocker_root.add_variable(ns_idx, node_id_str, initial)

            if writable:
                await n.set_writable()

            if change:
                change_nodes.append((n, variant_type))

    print(CONSOLE_BUILD_DONE)

    async def _on_client_write(event: Any, _callback_svc: Any = None) -> None:
        """客户端写值时：控制台打印并写文件日志。"""
        if not getattr(event, "is_external", True):
            return
        params = getattr(event, "request_params", None)
        if not params or not getattr(params, "NodesToWrite", None):
            return
        for wv in params.NodesToWrite:
            node_id = getattr(wv, "NodeId", None) or getattr(wv, "NodeId_", None)
            data_value = getattr(wv, "Value", None)
            val = data_value.Value.Value if data_value and getattr(data_value, "Value", None) else None
            msg = f"写值 NodeId={node_id} Value={val}"
            print(msg)
            logger.info(msg)

    server.subscribe_server_callback(CallbackType.PostWrite, _on_client_write)

    print(f"{CONSOLE_SERVER_START} {endpoint}")
    print(f"节点数量: {total_node_count}")
    print(CONSOLE_DESIGNED_BY)

    if change_nodes:
        async def _update_loop() -> None:
            while True:
                await asyncio.sleep(cycle_ms / 1000.0)
                for n, vt in change_nodes:
                    try:
                        cur = await n.get_value()
                        nxt = next_value(vt, cur)
                        await n.write_value(coerce_to_type(nxt, vt))
                    except Exception as e:
                        logger.debug("更新节点 %s 失败: %s", n, e)

        asyncio.create_task(_update_loop())

    logger.info("服务器已启动，cycle=%d ms，change 节点数=%d", cycle_ms, len(change_nodes))
    async with server:
        while True:
            await asyncio.sleep(3600)
