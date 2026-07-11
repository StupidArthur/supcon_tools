"""OPC UA 客户端：连 ua_mocker、浏览节点、读值。

对应闭环检查步骤 1：验证 ua_mocker 节点可达 + 节点存在。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import asyncua

from .mocker_yaml import MockerSpec


def connect_endpoint(spec_endpoint: str) -> str:
    """把 YAML 里的 endpoint 转成可连接的 endpoint。

    ua_mocker YAML 里 host 通常是 "0.0.0.0"（bind 地址），但 asyncua 客户端连不上
    0.0.0.0，需要把 host 替换成 localhost。
    """
    from urllib.parse import urlparse, urlunparse
    u = urlparse(spec_endpoint)
    host = u.hostname or ""
    if host in ("0.0.0.0", "::"):
        # 用 localhost 替代
        new_netloc = f"127.0.0.1:{u.port}"
        return urlunparse(u._replace(netloc=new_netloc))
    return spec_endpoint


@dataclass
class UaCheckResult:
    """步骤 1 的检查结果。"""
    passed: bool
    details: str
    sample_values: dict[str, Any]  # {node_id: value}，前 N 个节点的读值
    error: str | None = None


# ua_mocker 容器对象 BrowseName（见 ua_mocker/server_main.py:32）
CONTAINER_OBJECT_NAME = "mocker"


async def check_ua_server_async(
    endpoint: str,
    expected_node_ids: list[str],
    namespace_index: int = 1,
    sample_count: int = 3,
    timeout_seconds: float = 5.0,
) -> UaCheckResult:
    """异步：连 ua_mocker，浏览 /Objects/mocker，验证 expected 节点存在 + 读 sample_count 个值。

    Args:
        endpoint:          opc.tcp://host:port/ua_mocker/（0.0.0.0 会被替换为 127.0.0.1）
        expected_node_ids: [tag11, tag12, ...]（来自 MockerSpec.expected_node_ids）
        namespace_index:   YAML 里的 ns
        sample_count:      读前 N 个节点的值作为样本
        timeout_seconds:   asyncua 客户端超时
    """
    real_endpoint = connect_endpoint(endpoint)
    try:
        client = asyncua.Client(url=real_endpoint, timeout=timeout_seconds)
    except Exception as e:
        return UaCheckResult(
            passed=False, details="", sample_values={},
            error=f"创建客户端失败: {e}",
        )

    try:
        await client.connect()
    except Exception as e:
        return UaCheckResult(
            passed=False, details="", sample_values={},
            error=f"连接 {real_endpoint} 失败: {e}",
        )

    try:
        # 浏览 /Objects/<container>
        objects = await client.nodes.root.get_child(["0:Objects"])
        try:
            container = await objects.get_child(
                [f"{namespace_index}:{CONTAINER_OBJECT_NAME}"]
            )
        except Exception as e:
            return UaCheckResult(
                passed=False, details="", sample_values={},
                error=f"容器对象 /Objects/{CONTAINER_OBJECT_NAME} 不存在: {e}",
            )

        # 列出所有 children
        children = await container.get_children()
        existing_ids: set[str] = set()
        for child in children:
            try:
                qname = await child.read_browse_name()
                existing_ids.add(qname.Name)
            except Exception:
                # fallback 到 NodeId.Identifier
                nid = child.nodeid
                if nid.Identifier is not None:
                    existing_ids.add(str(nid.Identifier))

        # 验证所有 expected 节点都存在
        missing = [n for n in expected_node_ids if n not in existing_ids]
        if missing:
            return UaCheckResult(
                passed=False, details="", sample_values={},
                error=f"缺 {len(missing)} 个节点: {missing[:5]}{'...' if len(missing) > 5 else ''}",
            )

        # 读 sample_count 个值
        sample_values: dict[str, Any] = {}
        for nid in expected_node_ids[:sample_count]:
            try:
                node = await container.get_child(
                    [f"{namespace_index}:{nid}"]
                )
                sample_values[nid] = await node.read_value()
            except Exception as e:
                sample_values[nid] = f"<read failed: {e}>"

        return UaCheckResult(
            passed=True,
            details=f"{real_endpoint} (原始 {endpoint})，{len(existing_ids)} 个节点（共 {len(expected_node_ids)} 期望），前 {len(sample_values)} 个有值",
            sample_values=sample_values,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def check_ua_server(
    spec: MockerSpec,
    timeout_seconds: float = 5.0,
    sample_count: int = 3,
) -> UaCheckResult:
    """同步入口：跑步骤 1 检查。"""
    return asyncio.run(check_ua_server_async(
        endpoint=spec.endpoint,
        expected_node_ids=spec.all_expected_node_ids,
        namespace_index=spec.namespace_index,
        sample_count=sample_count,
        timeout_seconds=timeout_seconds,
    ))
