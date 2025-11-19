from app.core.unit_of_work import UnitOfWork
from app.core.redis_client import get_cache, set_cache, invalidate_caches
from app.tasks.ingestion_task import run_ingestion_task
from app.models.document import Document


class DocsService:
    """Handles creation, retrieval, and update of documents with caching and ingestion."""

    # -------------------------------------------------------------
    # 🔹 List all documents (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_all() -> list[dict]:
        cache_key = "docs:all"
        cached = await get_cache(cache_key)
        if cached:
            print("✅ [Redis] Cache hit for list_all()")
            return cached

        with UnitOfWork() as uow:
            docs = uow.documents.get_all()

        result = [
            {
                "id": d.id,
                "title": d.title,
                "source_url": d.source_url,
                "status": d.status,
                "departments": [dep.name for dep in d.departments],
                "is_active": getattr(d, "is_active", True),
            }
            for d in docs
        ]

        await set_cache(cache_key, result, expire_seconds=600)
        print("💾 [Redis] Cache set for list_all()")
        return result

    # -------------------------------------------------------------
    # 🔹 List documents allowed for a department (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_allowed(department_id: int) -> list[dict]:
        cache_key = f"docs:department:{department_id}"
        cached = await get_cache(cache_key)
        if cached:
            print(f"✅ [Redis] Cache hit for department {department_id}")
            return cached

        with UnitOfWork() as uow:
            docs = uow.documents.get_by_department(department_id)

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
        print(f"💾 [Redis] Cache set for department {department_id}")
        return result

    # -------------------------------------------------------------
    # 🔹 Add new document (trigger ingestion via Celery)
    # -------------------------------------------------------------
    @staticmethod
    async def add_document(title: str, source_url: str, department_ids: list[int]):
        with UnitOfWork() as uow:

            # Load departments
            departments = [uow.departments.get(dep_id) for dep_id in department_ids]
            if not all(departments):
                raise ValueError("No valid departments found for the provided IDs.")

            # Create doc
            new_doc = Document(
                title=title,
                source_url=source_url,
                is_active=True,
                status="pending",
            )

            uow.documents.save(new_doc)
            new_doc.departments = departments
            print(f"📄 Added new document {new_doc.id} ({title}) with status 'pending'.")

        # After UoW commit → dispatch ingestion
        run_ingestion_task.delay(new_doc.id, source_url, department_ids)
        print(f"🚀 [Celery] Dispatched ingestion task for document {new_doc.id}")

        return {"id": new_doc.id}

    # -------------------------------------------------------------
    # 🔹 Update permissions (invalidate caches)
    # -------------------------------------------------------------
    @staticmethod
    async def update_permissions(doc_id: int, department_ids: list[int]):
        with UnitOfWork() as uow:
            updated_doc = uow.documents.set_departments(doc_id, department_ids)

            if not updated_doc:
                raise ValueError("Document not found.")

        # Invalidate caches AFTER commit
        keys = ["docs:all"] + [f"docs:department:{dep_id}" for dep_id in department_ids]
        await invalidate_caches(keys)

        return {
            "message": "Permissions updated.",
            "departments": [d.name for d in updated_doc.departments],
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

        # Invalidate caches AFTER commit
        keys = ["docs:all"] + [
            f"docs:department:{dep_id}" for dep_id in affected_department_ids
        ]
        await invalidate_caches(keys)

        return {"message": f"Document {doc_id} deleted successfully."}
