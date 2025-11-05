# app/routers/ws.py
from fastapi import APIRouter, WebSocket
from app.core.websocket_manager import manager

router = APIRouter(tags=["websocket"])

@router.websocket("/documents/{doc_id}")
async def document_ws(websocket: WebSocket, doc_id: int):
    await manager.connect(doc_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except Exception:
        await manager.disconnect(doc_id)
