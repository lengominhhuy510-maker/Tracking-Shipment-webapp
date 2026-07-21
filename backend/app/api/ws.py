"""WebSocket endpoint and in-memory connection manager (IC§6)."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.jwt import verify_token

router = APIRouter()


class ConnectionManager:
    """Track active WebSocket clients and broadcast shipment updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: dict) -> None:
        disconnected: list[WebSocket] = []
        for connection in self.active_connections.copy():
            try:
                await connection.send_json(message)
            except (OSError, RuntimeError, WebSocketDisconnect):
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.cookies.get("session_token")
    if token is None or verify_token(token) is None:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
