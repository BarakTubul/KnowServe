# app/routers/admin/docs.py

from fastapi import APIRouter, HTTPException
from typing import List
from app.controllers.admin_docs_controller import AdminDocsController
from app.pydantic_schemas.document_schema import *
router = APIRouter()



# -------------------------
# Routes
# -------------------------

@router.get("/", summary="List all documents within the system")
async def list_all_documents():
    try:
        return await AdminDocsController.list_all_documents()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Something unexpected happened.")

@router.post("/", summary="Create a new document with owner & allowed access")
async def create_document(dto: CreateDocumentDTO):
    try:
        return await AdminDocsController.create_document(dto)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Something unexpected happened.")


@router.patch("/{doc_id}/access", summary="Update allowed departments for access")
async def update_document_access(doc_id: int, dto: UpdateAccessDTO):
    try:
        return await AdminDocsController.update_document_access(doc_id, dto)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Something unexpected happened.")


@router.delete("/{doc_id}", summary="Delete a document")
async def delete_document(doc_id: int):
    try:
        return await AdminDocsController.delete_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Something unexpected happened.")