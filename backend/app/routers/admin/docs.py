# app/routers/admin/docs.py
from fastapi import APIRouter, HTTPException
from typing import List
from app.services.docs_service import DocsService

router = APIRouter()

# ---------- CREATE ----------
@router.post("/", summary="Add a new document (multi-department)")
async def add_document(title: str, source_url: str, department_ids: List[int]):
    """
    Add a document and assign it to one or more departments.
    Example: department_ids=[1,2,3]
    """
    try:
        doc = await DocsService.add_document(title, source_url, department_ids)
        return {
            "message": "Document received.",
            "id": doc["id"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- READ ----------
@router.get("/", summary="List all documents")
async def list_all_documents():
    """Return all documents in the KB with their departments."""
    documents = await DocsService.list_all()
    return {"documents": documents}


# ---------- UPDATE ----------
@router.patch("/{doc_id}/permissions", summary="Update document departments")
async def update_document_permission(doc_id: int, department_ids: List[int]):
    """
    Update which departments can access this document.
    """
    try:
        return DocsService.update_permissions(doc_id, department_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- DELETE ----------
@router.delete("/{doc_id}", summary="Delete a document")
async def delete_document(doc_id: int):
    """Remove a document."""
    try:
        return await DocsService.delete_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
