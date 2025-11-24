# app/controllers/admin_docs_controller.py

from app.services.docs_service import DocsService


class AdminDocsController:

    @staticmethod
    async def add_document(title: str, source_url: str, department_ids: list[int]):
        return await DocsService.add_document(title, source_url, department_ids)

    @staticmethod
    async def update_permissions(doc_id: int, department_ids: list[int]):
        return await DocsService.update_permissions(doc_id, department_ids)

    @staticmethod
    async def delete_document(doc_id: int):
        return await DocsService.delete_document(doc_id)
