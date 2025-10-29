from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.services.docs_service import DocsService
from fastapi import UploadFile, File, Form

router = APIRouter()


# ---------- CREATE ----------
@router.post("/upload", summary="Upload multiple department documents")
async def upload_documents(files: List[UploadFile] = File(...), names: List[str] = Form(...), department_ids: List[int] = Form(...)):
    """
    Upload multiple documents to Google Drive and store metadata in the database.
    Each file is uploaded to its department folder and linked to the department(s) in DB.
    """
    try:
        uploaded_docs = await DocsService.upload_multiple(
            files,
            names,
            department_ids
        )

        return {
            "message": f"{len(uploaded_docs)} documents uploaded successfully.",
            "documents": uploaded_docs,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ---------- READ ----------
@router.get("/", summary="List all documents")
async def list_all_documents():
    """Return all documents in the knowledge base with their linked departments."""
    try:
        documents = await DocsService.list_all()
        return {"documents": documents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {str(e)}")


# ---------- UPDATE ----------
@router.patch("/{doc_id}/permissions", summary="Update document departments")
async def update_document_permission(doc_id: int, department_ids: List[int]):
    """Update which departments can access this document."""
    try:
        return await DocsService.update_permissions(doc_id, department_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


# ---------- DELETE ----------
@router.delete("/", summary="Delete multiple documents")
async def delete_documents(doc_ids: List[int]):
    """
    Delete multiple documents from Google Drive and the database.
    Example request body: [1, 2, 3]
    """
    try:
        result = await DocsService.delete_multiple(doc_ids)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")
