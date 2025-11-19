# app/controllers/ws_controller.py

from app.core.websocket_manager import manager
from fastapi import WebSocket


class WSController:

    @staticmethod
    async def document_connection(websocket: WebSocket, doc_id: int):
        """
        Handles the websocket lifecycle for a specific document.
        Router should not contain any logic.
        """
        await manager.connect(doc_id, websocket)

        try:
            while True:
                await websocket.receive_text()   # Keep connection alive
        except Exception:
            await manager.disconnect(doc_id)
