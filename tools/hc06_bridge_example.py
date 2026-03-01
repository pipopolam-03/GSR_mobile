"""
Пример минимального bridge для HC-06 -> WebSocket.

Это скелет: чтение HC-06 реализуйте удобным способом для вашей ОС
(например, RFCOMM/COM-порт), а затем отправляйте строку всем WS-клиентам.
"""

import asyncio
import json
from websockets.server import serve

clients = set()


async def ws_handler(websocket):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.remove(websocket)


async def fake_hc06_source():
    # Замените на реальное чтение HC-06
    value = 400
    while True:
        value += 1
        payload = json.dumps({"gsr": value})
        stale = []
        for ws in clients:
            try:
                await ws.send(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            clients.discard(ws)
        await asyncio.sleep(0.1)


async def main():
    async with serve(ws_handler, "0.0.0.0", 8765):
        await fake_hc06_source()


if __name__ == "__main__":
    asyncio.run(main())
