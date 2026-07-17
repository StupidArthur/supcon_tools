"""
OPCUA 测试客户端

连接 standalone OPCUA 服务器，读取和写入数据。
"""

from asyncua import Client, ua
import asyncio
import sys


async def main():
    url = "opc.tcp://127.0.0.1:18951"

    print(f"Connecting to OPCUA server at {url}...")

    async with Client(url) as client:
        print("Connected!")

        # 获取根节点
        root = client.get_root_node()
        print(f"Root node: {root}")

        # 获取 Objects 文件夹
        objects = client.get_objects_node()
        print(f"Objects node: {objects}")

        # 遍历 DataFactory 文件夹下的所有节点
        try:
            datafactory = await root.get_child(["0:Objects", "DataFactory"])
            print(f"DataFactory folder: {datafactory}")

            # 获取所有子节点
            children = await datafactory.get_children()
            print(f"\nFound {len(children)} nodes in DataFactory:")

            for child in children:
                try:
                    browse_name = await child.read_browse_name()
                    node_id = child.node_id
                    value = await child.read_value()
                    print(f"  - {browse_name.Name}: {value} (node_id={node_id})")
                except Exception as e:
                    print(f"  - Error reading node: {e}")

        except Exception as e:
            print(f"Could not access DataFactory folder: {e}")

        # 读取特定节点
        print("\n--- Reading specific nodes ---")

        node_names = ["sin1.out", "tank_1.level", "v_name.MV", "v_name.PV"]

        for name in node_names:
            try:
                node_id = ua.NodeId(name, 2)  # namespace index 2 for DataFactory
                node = client.get_node(node_id)
                value = await node.read_value()
                print(f"{name} = {value}")
            except Exception as e:
                print(f"{name}: Error - {e}")

        # 写入测试
        print("\n--- Write test ---")

        try:
            # 写入 valve_1.target_opening
            valve_node = client.get_node(ua.NodeId("valve_1.target_opening", 2))
            print(f"Current valve_1.target_opening: {await valve_node.read_value()}")
            await valve_node.write_value(ua.DataValue(ua.Variant(50.0, ua.VariantType.Double)))
            print(f"New valve_1.target_opening: {await valve_node.read_value()}")
        except Exception as e:
            print(f"Write error: {e}")

        # 读取 tank_1.level 多次，观察变化
        print("\n--- Monitoring tank_1.level ---")
        tank_node = client.get_node(ua.NodeId("tank_1.level", 2))

        for i in range(5):
            try:
                value = await tank_node.read_value()
                print(f"  Reading {i+1}: tank_1.level = {value}")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Error: {e}")

        print("\nTest completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
