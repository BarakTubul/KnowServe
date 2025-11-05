# app/core/websocket_manager.py
from fastapi import WebSocket
from typing import Dict

class WebSocketManager:
    def __init__(self):
        # key = document ID, value = WebSocket connection
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, doc_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[doc_id] = websocket
        print(f"🔌 [WebSocket] Client connected for document {doc_id}")

    async def disconnect(self, doc_id: int):
        ws = self.active_connections.pop(doc_id, None)
        if ws:
            print(f"🔌 [WebSocket] Client disconnected for document {doc_id}")

    async def send_status(self, doc_id: int, status: str, message: str = ""):
        ws = self.active_connections.get(doc_id)
        if ws:
            try:
                await ws.send_json({"doc_id": doc_id, "status": status, "message": message})
                print(f"📡 [WebSocket] Sent status update for doc {doc_id}: {status}")
            except Exception as e:
                print(f"⚠️ [WebSocket] Failed to send message: {e}")
manager = WebSocketManager()
