from app.models.document import Document
from app.models.department import Department
from app.core.database import SessionLocal
from app.core.redis_client import get_cache, set_cache, redis_client
from app.tasks.ingestion_task import run_ingestion_task
import asyncio


class DocsService:
    """Handles creation, retrieval, and update of documents with caching and ingestion."""

    # -------------------------------------------------------------
    # 🔹 List all documents (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_all() -> list[dict]:
        """Return all documents with their linked departments."""
        cache_key = "docs:all"
        cached = await get_cache(cache_key)
        if cached:
            print("✅ [Redis] Cache hit for list_all()")
            return cached

        db = SessionLocal()
        docs = db.query(Document).all()
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
        db.close()

        await set_cache(cache_key, result, expire_seconds=600)
        print("💾 [Redis] Cache set for list_all()")
        return result

    # -------------------------------------------------------------
    # 🔹 List documents allowed for a department (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_allowed(department_id: int) -> list[dict]:
        """Return documents accessible to a specific department."""
        cache_key = f"docs:department:{department_id}"
        cached = await get_cache(cache_key)
        if cached:
            print(f"✅ [Redis] Cache hit for department {department_id}")
            return cached

        db = SessionLocal()
        dept = db.query(Department).get(department_id)
        if not dept:
            db.close()
            return []

        result = [
            {
                "id": d.id,
                "title": d.title,
                "source_url": d.source_url,
                "status": d.status,
            }
            for d in dept.documents
        ]
        db.close()

        await set_cache(cache_key, result, expire_seconds=900)
        print(f"💾 [Redis] Cache set for department {department_id}")
        return result

    # -------------------------------------------------------------
    # 🔹 Add new document (trigger ingestion via Celery)
    # -------------------------------------------------------------
    @staticmethod
    async def add_document(title: str, source_url: str, department_ids: list[int]):
        """Create a new document, assign departments, and trigger ingestion."""
        db = SessionLocal()
        try:
            departments = (
                db.query(Department)
                .filter(Department.id.in_(department_ids))
                .all()
            )
            if not departments:
                raise ValueError("No valid departments found for the provided IDs.")

            # 🧱 Create document with status 'pending'
            new_doc = Document(
                title=title,
                source_url=source_url,
                is_active=True,
                status="pending",
            )
            new_doc.departments.extend(departments)
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)
            print(f"📄 Added new document {new_doc.id} ({title}) with status 'pending'.")

        finally:
            db.close()


        # 🚀 Dispatch Celery ingestion job
        run_ingestion_task.delay(new_doc.id, source_url, department_ids)
        print(f"🚀 [Celery] Dispatched ingestion task for document {new_doc.id}")

        # ✅ Return
        return {"id":new_doc.id}

    # -------------------------------------------------------------
    # 🔹 Update permissions (invalidate caches)
    # -------------------------------------------------------------
    @staticmethod
    async def update_permissions(doc_id: int, department_ids: list[int]):
        """Update which departments have access to the document."""
        db = SessionLocal()
        doc = db.query(Document).get(doc_id)
        if not doc:
            db.close()
            raise ValueError("Document not found.")

        departments = (
            db.query(Department)
            .filter(Department.id.in_(department_ids))
            .all()
        )
        doc.departments = departments
        db.commit()
        db.refresh(doc)
        db.close()

        # 🔄 Invalidate caches
        if redis_client:
            await redis_client.delete("docs:all")
            for dep_id in department_ids:
                await redis_client.delete(f"docs:department:{dep_id}")
            print("🧹 [Redis] Invalidated caches after update_permissions()")

        return {"message": "Permissions updated.", "departments": [d.name for d in departments]}

    # -------------------------------------------------------------
    # 🔹 Delete document (invalidate caches)
    # -------------------------------------------------------------
    @staticmethod
    async def delete_document(doc_id: int):
        """Delete a document and clear relevant caches."""
        db = SessionLocal()
        doc = db.query(Document).get(doc_id)
        if not doc:
            db.close()
            raise ValueError("Document not found.")

        affected_department_ids = [d.id for d in doc.departments]
        db.delete(doc)
        db.commit()
        db.close()

        # 🔄 Invalidate caches
        if redis_client:
            await redis_client.delete("docs:all")
            for dep_id in affected_department_ids:
                await redis_client.delete(f"docs:department:{dep_id}")
            print("🧹 [Redis] Invalidated caches after delete_document()")

        return {"message": f"Document {doc_id} deleted successfully."}
