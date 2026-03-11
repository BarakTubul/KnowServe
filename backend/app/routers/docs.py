from fastapi import APIRouter, Depends, HTTPException
from app.controllers.docs_controller import DocsController
from app.utils.auth import require_user_with_department, get_current_user

router = APIRouter(tags=["Documents"])

@router.get("/my/access", summary="List documents my department can access")
async def list_my_accessible_documents(current_user=Depends(require_user_with_department)):
    return await DocsController.list_allowed_docs(current_user)

@router.get("/my/owned", summary="Documents owned by my department")
async def list_my_owned_documents(current_user=Depends(require_user_with_department)):
    return await DocsController.list_my_owned_documents(current_user)

@router.get("/my/{doc_id}/download", summary="Download PDF securely")
async def download_document(
    doc_id: int, 
    current_user=Depends(get_current_user) # get_current_user parses cookies natively
):
    try:
        return await DocsController.download_document(doc_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Something unexpected happened.")