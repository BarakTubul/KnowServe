# app/routers/docs.py
from fastapi import APIRouter, HTTPException, Depends, status
from app.services.docs_service import DocsService
from app.utils.auth import require_user_with_department

router = APIRouter( tags=["Documents"])

@router.get("/my", summary="List documents for the user's own department")
async def list_my_department_docs(current_user=Depends(require_user_with_department)):
    """
    Returns all documents accessible to the user's department.
    Admins see all documents.
    """
    if current_user["role"] == "admin":
        documents = await DocsService.list_all()
    else:
        documents = await DocsService.list_allowed(current_user["department_id"])

    return {"documents": documents}

