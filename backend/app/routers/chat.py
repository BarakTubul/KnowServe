# app/routers/chat.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_chat_home():
    return {"message": "💬 Chat module placeholder"}


