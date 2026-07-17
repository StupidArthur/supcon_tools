import asyncio
import json
import websockets

async def test():
    async with websockets.connect("ws://127.0.0.1:8000/ws/snapshot") as ws:
        for i in range(5):
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(msg)
            if "_heartbeat" in data:
                print(f"heartbeat")
            else:
                cycle = data.get("cycle_count")
                level = data.get("tank_1.level", "N/A")
                sv = data.get("v_name.SV", "N/A")
                print(f"snapshot: cycle={cycle}, level={level}, SV={sv}")
        print("WS OK")

asyncio.run(test())
