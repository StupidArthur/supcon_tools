"""WS auth smoke helper used by realtime-auth-smoke.ps1.

Usage: python ws_auth_check.py <url> [<auth_header>] [<expected_close_code>]

- No auth header → must close with expected_close_code (typically 4401).
- With auth header → must connect and receive at least one message.
"""
import asyncio
import sys
import websockets


async def main():
    url = sys.argv[1]
    headers = []
    if len(sys.argv) > 2 and sys.argv[2]:
        headers.append(("Authorization", sys.argv[2]))
    want_code = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    try:
        async with websockets.connect(url, additional_headers=headers) as ws:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                print("WS_RECV " + (msg if isinstance(msg, str) else msg.decode("utf-8", "replace"))[:80])
                sys.exit(0)
            except Exception as e:
                print("WS_RECV_ERR " + str(e))
                sys.exit(2)
    except websockets.exceptions.ConnectionClosed as e:
        print("WS_CLOSED " + str(e.code))
        if want_code and e.code == want_code:
            sys.exit(0)
        sys.exit(2)
    except Exception as e:
        print("WS_ERR " + str(e))
        sys.exit(2)


asyncio.run(main())
