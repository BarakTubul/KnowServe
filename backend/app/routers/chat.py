# app/routers/chat.py
from fastapi import APIRouter
from app.pydantic_schemas.chat_schema import ChatRequest
from fastapi.responses import StreamingResponse
from app.services.chat_service import ChatService


router = APIRouter()
chat_service = ChatService()

@router.post("/chat-stream")
async def chat_stream(req: ChatRequest):

    async def streamer():
        async for token in chat_service.run_query_stream(req.messages, req.user):
            yield token

    return StreamingResponse(streamer(), media_type="text/plain")


