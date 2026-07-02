# -*- coding: utf-8 -*-
"""
OPC UA 可写节点测试客户端。

测试内容：
  1. 向可写浮点节点 test_write 写入值并读回验证
  2. 向可写布尔节点 test_bool_write 写入值并读回验证
  3. 向只读节点 LIC103.SV 尝试写入，验证是否被拒绝
"""

import asyncio
import sys

from asyncua import Client, ua

SERVER_URL = "opc.tcp://127.0.0.1:18950/"
NAMESPACE_INDEX = 1

WRITABLE_FLOAT_NODE = "test_write"
WRITABLE_BOOL_NODE = "test_bool_write"
READONLY_NODE = "LIC103.SV"


async def test_writable_float(client: Client) -> bool:
    node_id = f"ns={NAMESPACE_INDEX};s={WRITABLE_FLOAT_NODE}"
    node = client.get_node(node_id)

    test_value = 123.456
    print(f"  [写] {WRITABLE_FLOAT_NODE} <- {test_value}")
    await node.write_value(ua.Variant(test_value, ua.VariantType.Double))

    read_back = await node.read_value()
    print(f"  [读] {WRITABLE_FLOAT_NODE} -> {read_back}")

    if abs(read_back - test_value) < 0.001:
        print(f"  [PASS] 可写浮点节点写入/读取一致")
        return True
    else:
        print(f"  [FAIL] 期望 {test_value}，实际 {read_back}")
        return False


async def test_writable_bool(client: Client) -> bool:
    node_id = f"ns={NAMESPACE_INDEX};s={WRITABLE_BOOL_NODE}"
    node = client.get_node(node_id)

    test_value = True
    print(f"  [写] {WRITABLE_BOOL_NODE} <- {test_value}")
    await node.write_value(ua.Variant(test_value, ua.VariantType.Boolean))

    read_back = await node.read_value()
    print(f"  [读] {WRITABLE_BOOL_NODE} -> {read_back}")

    if read_back == test_value:
        print(f"  [PASS] 可写布尔节点写入/读取一致")
        return True
    else:
        print(f"  [FAIL] 期望 {test_value}，实际 {read_back}")
        return False


async def test_readonly_write_fails(client: Client) -> bool:
    node_id = f"ns={NAMESPACE_INDEX};s={READONLY_NODE}"
    node = client.get_node(node_id)

    print(f"  [写] {READONLY_NODE} <- 999.0 (预期失败)")
    try:
        await node.write_value(ua.Variant(999.0, ua.VariantType.Double))
        print(f"  [FAIL] 只读节点写入居然成功了，不应该")
        return False
    except ua.UaStatusCodeError as e:
        print(f"  [读] 写入被拒绝: {e}")
        print(f"  [PASS] 只读节点正确拒绝了写入")
        return True
    except Exception as e:
        print(f"  [读] 写入异常: {type(e).__name__}: {e}")
        print(f"  [PASS] 只读节点写入失败（异常方式）")
        return True


async def main():
    print(f"连接 OPC UA 服务器: {SERVER_URL}")
    client = Client(url=SERVER_URL)
    try:
        await client.connect()
        print("连接成功\n")
    except Exception as e:
        print(f"连接失败: {e}")
        print("请确保服务端已启动: python main.py data_test_write.csv")
        return 1

    results = []

    print("=" * 50)
    print("测试 1: 可写浮点节点")
    print("=" * 50)
    results.append(await test_writable_float(client))

    print()
    print("=" * 50)
    print("测试 2: 可写布尔节点")
    print("=" * 50)
    results.append(await test_writable_bool(client))

    print()
    print("=" * 50)
    print("测试 3: 只读节点写入应被拒绝")
    print("=" * 50)
    results.append(await test_readonly_write_fails(client))

    await client.disconnect()

    print()
    print("=" * 50)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"全部通过: {passed}/{total}")
        return 0
    else:
        print(f"部分失败: {passed}/{total}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))