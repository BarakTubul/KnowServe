from app.core.unit_of_work import UnitOfWork
from app.core.redis_client import get_cache, set_cache, invalidate_caches
from app.tasks.ingestion_task import run_ingestion_task
from app.models.document import Document
from app.services.ingestion_service import DocumentIngestionService


class DocsService:
    """Handles creation, retrieval, ownership, and access control for documents."""

    # -------------------------------------------------------------
    # 🔹 List ALL documents (admin, cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_all_documents() -> list[dict]:
        cache_key = "docs:all"
        cached = await get_cache(cache_key)
        if cached:
            print("✅ [Redis] Cache hit for list_all_documents()")
            return cached

        with UnitOfWork() as uow:
            docs = uow.documents.get_all()

            result = [
                {
                    "id": d.id,
                    "title": d.title,
                    "source_url": d.source_url,
                    "status": d.status,
                    "allowed_departments": [dep.name for dep in d.departments],
                    "owner_department_id": getattr(d, "owner_department_id", None),
                    "is_active": getattr(d, "is_active", True),
                }
                for d in docs
            ]

        await set_cache(cache_key, result, expire_seconds=600)
        print("💾 [Redis] Cache set for list_all_documents()")
        return result

    # -------------------------------------------------------------
    # 🔹 List documents a department IS ALLOWED to access (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_documents_with_access(department_id: int) -> list[dict]:
        cache_key = f"docs:access:{department_id}"
        cached = await get_cache(cache_key)

        if cached:
            print(f"✅ [Redis] Cache hit for access of department {department_id}")
            return cached

        with UnitOfWork() as uow:
            docs = uow.documents.get_documents_with_access_for_department(department_id)

            result = [
                {
                    "id": d.id,
                    "title": d.title,
                    "source_url": d.source_url,
                    "status": d.status,
                }
                for d in docs
            ]

        await set_cache(cache_key, result, expire_seconds=900)
        print(f"💾 [Redis] Cache set for department access {department_id}")
        return result

    # -------------------------------------------------------------
    # 🔹 List documents OWNED by a department
    # -------------------------------------------------------------
    @staticmethod
    async def list_owned_documents(department_id: int) -> list[dict]:
        with UnitOfWork() as uow:
            docs = uow.documents.get_documents_owned_by_department(department_id)

            return [
                {
                    "id": d.id,
                    "title": d.title,
                    "source_url": d.source_url,
                    "status": d.status,
                }
                for d in docs
            ]

    # -------------------------------------------------------------
    # 🔹 Add new document (sets owner + allowed access + ingestion)
    # -------------------------------------------------------------
    @staticmethod
    async def add_document(title: str, source_url: str, owner_department_id: int, allowed_department_ids: list[int]):
        with UnitOfWork() as uow:

            # Load allowed departments
            allowed_departments = [
                uow.departments.get(dep_id) for dep_id in allowed_department_ids
            ]
            if not all(allowed_departments):
                raise ValueError("One or more allowed department IDs are invalid.")

            # Load owner
            owner = uow.departments.get(owner_department_id)
            if not owner:
                raise ValueError("Invalid owner_department_id provided.")

            # Create document
            new_doc = Document(
                title=title,
                source_url=source_url,
                is_active=True,
                status="pending",
                owner_department_id=owner_department_id,
            )

            uow.documents.save(new_doc)
            new_doc.departments = allowed_departments
            new_doc_id = new_doc.id

            print(f"📄 Created document {new_doc_id} owned by department {owner_department_id}")

        # Kick off ingestion after commit
        run_ingestion_task.delay(new_doc_id, source_url, allowed_department_ids)
        print(f"🚀 [Celery] Ingestion task dispatched for document {new_doc_id}")

        return {"id": new_doc_id}

    # -------------------------------------------------------------
    # 🔹 Update document access control (permissions)
    # -------------------------------------------------------------
    @staticmethod
    async def update_document_access(doc_id: int, new_allowed_department_ids: list[int]):
        with UnitOfWork() as uow:
            updated_doc = uow.documents.set_document_access(doc_id, new_allowed_department_ids)

            if not updated_doc:
                raise ValueError("Document not found.")

            allowed_names = [d.name for d in updated_doc.departments]

        # Invalidate caches that depend on access
        keys = ["docs:all"] + [f"docs:access:{dep_id}" for dep_id in new_allowed_department_ids]
        await invalidate_caches(keys)

        return {
            "message": "Access permissions updated.",
            "allowed_departments": allowed_names,
        }

    # -------------------------------------------------------------
    # 🔹 Delete document (invalidate caches)
    # -------------------------------------------------------------
    @staticmethod
    async def delete_document(doc_id: int):
        with UnitOfWork() as uow:
            doc = uow.documents.get(doc_id)
            if not doc:
                raise ValueError("Document not found.")

            affected_department_ids = [d.id for d in doc.departments]
            uow.documents.delete(doc)

        keys = ["docs:all"] + [f"docs:access:{dep_id}" for dep_id in affected_department_ids]
        await invalidate_caches(keys)

        return {"message": f"Document {doc_id} deleted successfully."}

    @staticmethod
    async def get_document_text(doc_id: int, user: dict) -> dict:
    # 1. Permission check
        allowed_docs = []
        for dep_id in user.get("departments", []):
            allowed_docs.extend(await DocsService.list_documents_with_access(dep_id))

        if not any(doc["id"] == doc_id for doc in allowed_docs):
            raise ValueError("No Access to this doc!")

        # 2. Load metadata from DB
        with UnitOfWork() as uow:
            doc = uow.documents.get(doc_id)
            if not doc:
                raise ValueError("Document not found.")
            result = {
                    "id": doc.id,
                    "title": doc.title,
                    "source_url": doc.source_url,
            }              

        # 3. Extract text
        full_text = DocumentIngestionService.extract_text_from_url(result["source_url"])
        result["content"] = full_text
        return result
