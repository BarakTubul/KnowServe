# app/routers/admin/docs.py

from fastapi import APIRouter, HTTPException
from typing import List
from app.controllers.admin_docs_controller import AdminDocsController

router = APIRouter()


@router.post("/", summary="Add a new document")
async def add_document(title: str, source_url: str, department_ids: List[int]):
    try:
        return await AdminDocsController.add_document(title, source_url, department_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{doc_id}/permissions", summary="Update document departments")
async def update_permissions(doc_id: int, department_ids: List[int]):
    try:
        return await AdminDocsController.update_permissions(doc_id, department_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{doc_id}", summary="Delete a document")
async def delete_document(doc_id: int):
    try:
        return await AdminDocsController.delete_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
