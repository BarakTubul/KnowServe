# app/routers/admin/docs.py
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.services.docs_service import DocsService
from app.schemas.docs_schema import DocumentUploadForm

router = APIRouter()

# ---------- CREATE ----------
@router.post("/upload", summary="Upload multiple department documents")
async def upload_documents(form: DocumentUploadForm = Depends()):
    """
    Upload multiple named documents to Google Drive and store metadata in DB.
    Each document gets its own name and is linked to one or more departments.
    """
    try:
        uploaded_docs = []

        for file, name in zip(form.files, form.names):
            doc = await DocsService.upload_to_drive_and_add_doc(
                file=file,
                name=name,
                department_name=form.department_name,
                department_ids=form.department_ids,
            )
            uploaded_docs.append({
                "id": doc.id,
                "title": doc.title,
                "source_url": doc.source_url,
            })

        return {
            "message": f"{len(uploaded_docs)} documents uploaded successfully.",
            "documents": uploaded_docs,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


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
@router.delete("/", summary="Delete multiple documents")
async def delete_documents(doc_ids: List[int]):
    """
    Delete multiple documents from the database and Google Drive.
    Example request body: [1, 2, 3]
    """
    try:
        results = []
        for doc_id in doc_ids:
            result = await DocsService.delete_document(doc_id)
            results.append(result)

        return {
            "message": f"{len(results)} document(s) deleted successfully.",
            "results": results,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")
