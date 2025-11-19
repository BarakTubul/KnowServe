from fastapi import APIRouter, Depends
from app.controllers.docs_controller import DocsController
from app.utils.auth import require_user_with_department

router = APIRouter(tags=["Documents"])

@router.get("/my")
async def list_my_docs(current_user=Depends(require_user_with_department)):
    return await DocsController.list_my_docs(current_user)
