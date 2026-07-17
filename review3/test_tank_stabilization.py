"""
水箱液位控制测试

测试流程：
1. 启动仿真，初始记录阶段（约60秒）
2. 通过 OPCUA 修改 SV（设定值）
3. 继续记录数据（约60秒）
4. 全程记录所有参数到 CSV
"""

from asyncua import Client, ua
import asyncio
import csv
import sys
import time
from datetime import datetime


# 配置
OPCUA_URL = "opc.tcp://127.0.0.1:18951"
CSV_OUTPUT = "tank_test_results.csv"

# 监控的参数节点名
MONITORED_NODES = [
    "sin1.out",
    "source_flow",
    "valve_1.target_opening",
    "valve_1.current_opening",
    "valve_1.outlet_flow",
    "tank_1.level",
    "v_name.MV",
    "v_name.PV",
    "v_name.SV",
]

# 测试阶段
INITIAL_DURATION = 60  # 初始记录阶段（秒）
POST_CHANGE_DURATION = 60  # 改 SV 后记录阶段（秒）


async def read_all_values(client: Client) -> dict:
    """读取所有监控节点的值"""
    result = {}
    for node_name in MONITORED_NODES:
        try:
            node_id = ua.NodeId(node_name, 2)
            node = client.get_node(node_id)
            value = await node.read_value()
            result[node_name] = value
        except Exception as e:
            result[node_name] = None
    return result


async def change_sv(client: Client, new_sv: float) -> None:
    """修改 SV 设定值"""
    print(f"  Changing SV to {new_sv}...")
    try:
        node_id = ua.NodeId("v_name.SV", 2)
        node = client.get_node(node_id)
        await node.write_value(ua.DataValue(ua.Variant(new_sv, ua.VariantType.Double)))
        print(f"  ✓ SV changed to {new_sv}")
    except Exception as e:
        print(f"  ✗ Failed to change SV: {e}")
        raise


async def main():
    print("=" * 60)
    print("Water Tank Stabilization Test")
    print("=" * 60)
    print(f"OPCUA URL: {OPCUA_URL}")
    print(f"Output CSV: {CSV_OUTPUT}")
    print(f"Initial phase: {INITIAL_DURATION}s")
    print(f"Post-change phase: {POST_CHANGE_DURATION}s")
    print()

    # 连接 OPCUA
    print("Connecting to OPCUA server...")
    async with Client(OPCUA_URL) as client:
        print("Connected!")
        print()

        # 打开 CSV 文件准备写入
        csv_file = open(CSV_OUTPUT, 'w', newline='')
        csv_writer = csv.writer(csv_file)

        # 写入表头
        csv_writer.writerow(["timestamp", "elapsed_seconds", "phase"] + MONITORED_NODES)
        csv_file.flush()

        start_time = time.time()
        phase = "initial"

        try:
            # 阶段 1: 初始记录阶段
            print(f"Phase 1: Recording initial state for {INITIAL_DURATION} seconds...")
            phase_end_time = start_time + INITIAL_DURATION

            while time.time() < phase_end_time:
                all_values = await read_all_values(client)
                elapsed = time.time() - start_time
                timestamp = datetime.now().isoformat()
                row = [timestamp, f"{elapsed:.1f}", phase] + [all_values.get(n) for n in MONITORED_NODES]
                csv_writer.writerow(row)
                csv_file.flush()

                # 每秒打印一次当前状态
                pv = all_values.get("tank_1.level")
                sv = all_values.get("v_name.SV")
                print(f"  [{elapsed:.0f}s] PV={pv:.4f}, SV={sv:.4f}" if pv and sv else f"  [{elapsed:.0f}s] reading...")

                await asyncio.sleep(1)

            # 记录当前 SV 值
            current_values = await read_all_values(client)
            current_sv = current_values.get("v_name.SV", 1.0)
            print(f"Current SV = {current_sv}")

            # 阶段 2: 修改 SV
            print()
            print("Phase 2: Changing SV...")
            new_sv = current_sv + 0.5  # 增加 0.5
            await change_sv(client, new_sv)

            # 阶段 3: 改 SV 后继续记录
            print()
            print(f"Phase 3: Recording for {POST_CHANGE_DURATION} seconds after SV change...")
            phase = "post_change"
            phase_end_time = time.time() + POST_CHANGE_DURATION

            while time.time() < phase_end_time:
                all_values = await read_all_values(client)
                elapsed = time.time() - start_time
                timestamp = datetime.now().isoformat()
                row = [timestamp, f"{elapsed:.1f}", phase] + [all_values.get(n) for n in MONITORED_NODES]
                csv_writer.writerow(row)
                csv_file.flush()

                pv = all_values.get("tank_1.level")
                sv = all_values.get("v_name.SV")
                print(f"  [{elapsed:.0f}s] PV={pv:.4f}, SV={sv:.4f}" if pv and sv else f"  [{elapsed:.0f}s] reading...")

                await asyncio.sleep(1)

            print()
            print("=" * 60)
            print("Test completed!")
            print(f"Results saved to: {CSV_OUTPUT}")

        finally:
            csv_file.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
