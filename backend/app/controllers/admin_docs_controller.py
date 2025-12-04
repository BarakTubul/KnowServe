from app.services.docs_service import DocsService

class AdminDocsController:

    @staticmethod
    async def create_document(dto):
        return await DocsService.add_document(
            title=dto.title,
            source_url=dto.source_url,
            owner_department_id=dto.owner_department_id,
            allowed_department_ids=dto.allowed_department_ids,
        )

    @staticmethod
    async def update_document_access(doc_id: int, dto):
        return await DocsService.update_document_access(
            doc_id,
            dto.allowed_department_ids
        )

    @staticmethod
    async def delete_document(doc_id: int):
        return await DocsService.delete_document(doc_id)
