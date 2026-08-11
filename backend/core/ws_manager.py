"""
ws_manager.py

Tracks connected WebSocket clients and broadcasts status updates to all
of them at once. Kept separate from poller.py so the poller doesn't need
to know anything about WebSocket internals - it just calls broadcast()
with a plain dict after each successful poll.
"""

import asyncio
import logging

from fastapi import WebSocket

_LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        _LOGGER.info("WebSocket client connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        _LOGGER.info("WebSocket client disconnected (%d total)", len(self._connections))

    async def broadcast(self, payload: dict):
        async with self._lock:
            connections = list(self._connections)

        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                # Connection is most likely already gone - clean it up
                # rather than letting a dead socket linger in the list
                # and fail on every future broadcast too.
                await self.disconnect(ws)


manager = ConnectionManager()
