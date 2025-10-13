# app/routers/docs.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_docs_home():
    return {"message": "📚 Document management placeholder"}


