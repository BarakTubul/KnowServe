from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.pydantic_schemas.chat_schema import ChatRequest
from app.services.chat_service import ChatService
from app.utils.auth import get_current_user

router = APIRouter()
chat_service = ChatService()


@router.post("/stream")
async def stream_chat(
    request: ChatRequest, 
    current_user: dict = Depends(get_current_user)
):
    return StreamingResponse(
    ChatService.get_streaming_chat_response(request.messages, current_user),
    media_type="text/event-stream"
)
