# app/routers/admin.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_admin_dashboard():
    return {"message": "🧩 Admin dashboard placeholder"}


