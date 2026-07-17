"""Start server, test WebSocket, stop server. All in one."""
import subprocess
import sys
import time
import json
import asyncio
import websockets

proc = subprocess.Popen(
    [sys.executable, "standalone_main.py", "-c", "config/tank_constant_sv.yaml", "--api"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(6)

async def test():
    async with websockets.connect("ws://127.0.0.1:8000/ws/snapshot") as ws:
        for i in range(3):
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            if "_heartbeat" not in data:
                cycle = data.get("cycle_count")
                level = data.get("tank_1.level", "N/A")
                print(f"  cycle={cycle}, level=%.3f" % level)
        print("WS OK")

try:
    asyncio.run(test())
except Exception as e:
    print(f"WS FAIL: {e}")
finally:
    proc.terminate()
    proc.wait(timeout=5)
    print("Server stopped")
