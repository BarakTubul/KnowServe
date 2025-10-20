# app/routers/docs.py
from fastapi import APIRouter
from app.services.docs_service import DocsService

router = APIRouter( tags=["Documents"])

@router.get("/", summary="List allowed documents for a department")
async def get_allowed_documents(department_id: int):
    """
    Return all documents accessible to a specific department.
    Accessible to regular authenticated users.
    """
    return {"documents": DocsService.list_allowed(department_id)}
