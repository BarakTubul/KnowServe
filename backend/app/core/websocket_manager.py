# app/core/websocket_manager.py
from fastapi import WebSocket
from typing import Dict, List

class WebSocketManager:
    def __init__(self):
        # key = document ID, value = WebSocket connection
        self.active_connections: Dict[int, WebSocket] = {}
        # store pending messages for documents whose clients haven’t connected yet
        self.pending_messages: Dict[int, List[dict]] = {}

    async def connect(self, doc_id: int, websocket: WebSocket):
        """
        Accept a new websocket connection for a document.
        If there are any pending messages for this document, send them immediately.
        """
        await websocket.accept()
        self.active_connections[doc_id] = websocket
        print(f"🔌 [WebSocket] Client connected for document {doc_id}")

        # flush pending messages (if ingestion finished before client connected)
        if doc_id in self.pending_messages:
            for msg in self.pending_messages[doc_id]:
                await websocket.send_json(msg)
                print(f"📤 [WebSocket] Flushed buffered message for doc {doc_id}: {msg}")
            self.pending_messages.pop(doc_id, None)

    async def disconnect(self, doc_id: int):
        """
        Remove a websocket connection for a document.
        """
        ws = self.active_connections.pop(doc_id, None)
        if ws:
            print(f"🔌 [WebSocket] Client disconnected for document {doc_id}")

    async def send_status(self, doc_id: int, status: str, message: str = ""):
        """
        Send a status update to the websocket client for this document.
        If no active connection exists yet, buffer the message to send later.
        """
        ws = self.active_connections.get(doc_id)
        payload = {"doc_id": doc_id, "status": status, "message": message}

        if ws:
            try:
                await ws.send_json(payload)
                print(f"📡 [WebSocket] Sent status update for doc {doc_id}: {status}")
            except Exception as e:
                print(f"⚠️ [WebSocket] Failed to send message for doc {doc_id}: {e}")
        else:
            # Buffer for later if client isn’t connected yet
            self.pending_messages.setdefault(doc_id, []).append(payload)
            print(f"🕒 [WebSocket] Buffered message for doc {doc_id}: {status}")

manager = WebSocketManager()
