# app/routers/ws.py

from fastapi import APIRouter, WebSocket
from app.controllers.ws_controller import WSController

router = APIRouter(tags=["WebSocket"])


@router.websocket("/documents/{doc_id}")
async def document_ws(websocket: WebSocket, doc_id: int):
    await WSController.document_connection(websocket, doc_id)
