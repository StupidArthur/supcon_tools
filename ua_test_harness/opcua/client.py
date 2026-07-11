"""OPC UA 源端 client(asyncua 封装):直连 ua_mocker/ua_player,读/写/发现节点。

绕过 TPT,用于:
- 验证 mock 节点确实存在 / 可读 / 可写
- 写源端值,再查 TPT RT/history 看传播
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from asyncua import Client


@dataclass
class NodeInfo:
    browse_name: str
    node_id: str
    value: object = None


class UaSourceClient:
    def __init__(self, endpoint: str, namespace_index: int = 1):
        self.endpoint = endpoint
        self.ns = namespace_index

    def _nid(self, name: str) -> str:
        return f"ns={self.ns};s={name}"

    async def read(self, name: str):
        async with Client(self.endpoint) as client:
            return await client.get_node(self._nid(name)).read_value()

    async def write(self, name: str, value):
        async with Client(self.endpoint) as client:
            await client.get_node(self._nid(name)).write_value(value)

    async def read_many(self, names: list[str]) -> dict:
        out: dict = {}
        async with Client(self.endpoint) as client:
            for n in names:
                try:
                    out[n] = await client.get_node(self._nid(n)).read_value()
                except Exception as e:
                    out[n] = f"<err: {e}>"
        return out

    async def discover(self) -> list[NodeInfo]:
        """列出 Objects 下本 namespace 的节点。"""
        infos: list[NodeInfo] = []
        async with Client(self.endpoint) as client:
            objects = client.get_objects_node()
            for ch in await objects.get_children():
                bn = await ch.read_browse_name()
                if bn.NamespaceIndex == self.ns:
                    nid = ch.nodeid.to_string()
                    val = None
                    try:
                        val = await ch.read_value()
                    except Exception:
                        pass
                    infos.append(NodeInfo(browse_name=bn.Name, node_id=nid, value=val))
        return infos

    # ---- 同步包装 ----
    def read_sync(self, name: str):
        return asyncio.run(self.read(name))

    def write_sync(self, name: str, value):
        return asyncio.run(self.write(name, value))

    def discover_sync(self) -> list[NodeInfo]:
        return asyncio.run(self.discover())
