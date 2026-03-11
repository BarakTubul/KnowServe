from app.services.docs_service import DocsService
from fastapi.responses import FileResponse

class DocsController:

    @staticmethod
    async def list_allowed_docs(current_user):
        # Admins see everything
        if current_user["role"] == "admin":
            return await DocsService.list_all_documents()

        # Regular employees/managers see department docs
        department_id = current_user["department_id"]
        return await DocsService.list_documents_with_access(department_id)

    
    @staticmethod
    async def list_my_owned_documents(user):
        """Documents that originated from (are owned by) the user's department."""
        return await DocsService.list_owned_documents(user["department_id"])

    @staticmethod
    async def download_document(doc_id: int, current_user: dict):
        """Fetches the physical file path securely and returns a FileResponse."""
        file_path = await DocsService.get_document_file_path(doc_id, current_user)
        return FileResponse(path=file_path, filename=f"Document_{doc_id}.pdf", media_type="application/pdf")