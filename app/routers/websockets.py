from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws_manager import manager

router = APIRouter(tags=["websockets"])


@router.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    """Generic live-update channel. The Next.js dashboard connects to
    /ws/alerts and /ws/conveyor to get instant tile updates instead of
    polling. (MVP: no auth handshake on the socket itself; the page that
    opens it is already behind the admin login.)"""
    await manager.connect(channel, websocket)
    try:
        while True:
            # We don't expect client->server messages; just keep the
            # connection open and drop it cleanly on disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)
