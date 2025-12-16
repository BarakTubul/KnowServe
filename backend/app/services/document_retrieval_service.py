from app.services.docs_service import DocsService
from app.core.vector_store import get_vector_store

class DocumentRetrievalService:
    """
    High-level retrieval:
    - enforces permissions
    - runs vector similarity search
    - returns LLM-ready context
    """

    @staticmethod
    async def search(query: str, user: dict, k: int = 6):
        # 1️⃣ Get allowed documents
        allowed_doc_ids = set()
        for dep_id in user.get("departments", []):
            docs = await DocsService.list_documents_with_access(dep_id)
            for d in docs:
                allowed_doc_ids.add(d["id"])

        if not allowed_doc_ids:
            return []

        # 2️⃣ Vector search
        vector_store = get_vector_store()
        results = vector_store.similarity_search(
            query,
            k=k  
        )

        # 3️⃣ Filter by permissions
        filtered = [
            r for r in results
            if r.metadata.get("doc_id") in allowed_doc_ids
        ]

        # 4️⃣ Trim + shape
        return [
            {
                "content": r.page_content,
                "doc_id": r.metadata.get("doc_id"),
                "score": getattr(r, "score", None)
            }
            for r in filtered[:k]
        ]
