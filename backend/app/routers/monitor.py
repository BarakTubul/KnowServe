# app/routers/monitor.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def monitor_home():
    return {"message": "🧠 Monitor route placeholder"}
