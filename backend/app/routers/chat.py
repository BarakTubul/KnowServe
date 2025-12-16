# app/routers/chat.py
from fastapi import APIRouter,Depends
from app.pydantic_schemas.chat_schema import ChatRequest
from fastapi.responses import StreamingResponse
from app.services.chat_service import ChatService
from app.utils.auth import get_current_user


router = APIRouter()
chat_service = ChatService()

@router.post("/chat-stream")
async def chat_stream(req: ChatRequest, user = Depends(get_current_user)):

    async def streamer():
        try:
            async for token in chat_service.run_query_stream(req.messages, user):
                yield token
        except Exception as e:
            # SAFE ERROR STREAM
            yield f"[ERROR] {str(e)}"

    return StreamingResponse(streamer(), media_type="text/plain")



