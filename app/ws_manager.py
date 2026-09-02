import json
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Tiny pub/sub manager for the dashboard's live WebSocket channels
    (e.g. "alerts", "conveyor"). Broadcasts JSON-serializable payloads to
    every client currently subscribed to a channel."""

    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._channels[channel].add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        self._channels[channel].discard(websocket)

    async def broadcast(self, channel: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        message = json.dumps(payload, default=str)
        for ws in self._channels.get(channel, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._channels[channel].discard(ws)


manager = ConnectionManager()
