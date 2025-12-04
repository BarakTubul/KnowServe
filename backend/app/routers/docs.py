from fastapi import APIRouter, Depends
from app.controllers.docs_controller import DocsController
from app.utils.auth import require_user_with_department

router = APIRouter(tags=["Documents"])

@router.get("/my/access", summary="List documents my department can access")
async def list_my_accessible_documents(current_user=Depends(require_user_with_department)):
    return await DocsController.list_allowed_docs(current_user)


@router.get("/my/owned", summary="Documents owned by my department")
async def list_my_owned_documents(current_user=Depends(require_user_with_department)):
    return await DocsController.list_my_owned_documents(current_user)