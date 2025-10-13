# app/routers/auth.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def test_auth():
    return {"message": "Auth router placeholder"}
