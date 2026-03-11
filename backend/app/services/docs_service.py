import os
from app.core.unit_of_work import UnitOfWork
from app.core.redis_client import get_cache, set_cache, invalidate_caches
from app.tasks.ingestion_task import run_ingestion_task
from app.models.document import Document
from app.services.ingestion_service import DocumentIngestionService
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
from app.core.vector_store import get_llama_index
from app.core.chroma_client import get_chroma_client


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
                    "allowed_department_ids": [dep.id for dep in d.departments],
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
                    "allowed_departments": [dep.name for dep in d.departments],
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
    async def add_document(title: str, source_url: str, allowed_department_ids: list[int]):
        with UnitOfWork() as uow:

            # Load allowed departments
            allowed_departments = [
                uow.departments.get(dep_id) for dep_id in allowed_department_ids
            ]
            if not all(allowed_departments):
                raise ValueError("One or more allowed department IDs are invalid.")

            # Create document
            new_doc = Document(
                title=title,
                source_url=source_url,
                is_active=True,
                status="pending",
            )

            uow.documents.save(new_doc)
            new_doc.departments = allowed_departments
            new_doc_id = new_doc.id

            print(f"📄 Created document {new_doc_id}")

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
            # 1. Update the relational DB
            updated_doc = uow.documents.set_document_access(doc_id, new_allowed_department_ids)
            if not updated_doc:
                raise ValueError("Document not found.")

            allowed_names = [d.name for d in updated_doc.departments]
        
        # Vector store permissions are no longer synced (handled in PostgreSQL)

        # 3. Invalidate caches
        keys = ["docs:all"] + [f"docs:access:{dep_id}" for dep_id in new_allowed_department_ids]
        await invalidate_caches(keys)

        return {
            "message": "Access permissions updated in DB.",
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
        # Sync deletion to ChromaDB
        # We perform this after the DB commit to ensure consistency
        await DocsService.delete_from_vector_store(doc_id)

        keys = ["docs:all"] + [f"docs:access:{dep_id}" for dep_id in affected_department_ids]
        await invalidate_caches(keys)

        return {"message": f"Document {doc_id} deleted successfully."}

    @staticmethod
    async def delete_from_vector_store(doc_id: int):
        """Removes all nodes associated with a doc_id from ChromaDB."""
        from app.core.chroma_client import get_chroma_client
        client = get_chroma_client()
        collection = client.get_or_create_collection("documents")
        
        # Use a metadata filter to identify all chunks/nodes for this document
        # This ensures all split parts are removed at once
        collection.delete(where={"db_doc_id": doc_id})
        print(f"🗑️ [Chroma] All nodes for doc_id {doc_id} have been deleted.")
    
    @staticmethod
    async def get_document_text(doc_id: int, user: dict) -> dict:
        """
        LlamaIndex version: Retrieves text nodes from ChromaDB.
        """

        # 1. Check permissions in PostgreSQL
        user_dept_ids = user.get("departments", [])
        if not user_dept_ids:
            raise ValueError("User has no department access.")

        allowed = False
        for dept_id in user_dept_ids:
            docs = await DocsService.list_documents_with_access(dept_id)
            if any(doc["id"] == doc_id for doc in docs):
                allowed = True
                break

        if not allowed:
            raise ValueError("You do not have permission to access this document.")

        # 2. Setup Index and Filters
        index = get_llama_index()
        filters = MetadataFilters(filters=[
            ExactMatchFilter(key="db_doc_id", value=doc_id)
        ])

        # 3. Retrieve Nodes
        # We use a retriever to get all nodes matching the doc_id
        retriever = index.as_retriever(filters=filters)
        print("Querying LlamaIndex with filters:", filters)
        nodes = await retriever.aretrieve(f"Retrieve all text for document {doc_id}")
        
        if not nodes:
            print(f"LlamaIndex returned 0 nodes for doc_id {doc_id} with exact match filter!")
            raise ValueError("No Access or document is empty!")

        # 4. Reconstruct Document
        # LlamaIndex nodes store their original text and metadata
        full_text = "\n".join([node.get_content() for node in nodes])
        
        return {
            "id": doc_id,
            "content": full_text
        }

    @staticmethod
    async def get_document_file_path(doc_id: int, current_user: dict) -> str:
        """
        Validates user permissions and resolves the physical file path of a document PDF.
        """
        user_dept_ids = current_user.get("departments", [])
        if "department_id" in current_user and current_user["department_id"] not in user_dept_ids:
            if current_user["department_id"] is not None:
                user_dept_ids.append(current_user["department_id"])

        allowed = False
        
        # 1. Check if user is Admin
        if current_user.get("role") == "admin":
            allowed = True
        else:
            # 2. Check document permissions across all the user's mapped departments
            for dept_id in user_dept_ids:
                docs = await DocsService.list_documents_with_access(dept_id)
                if any(doc["id"] == doc_id for doc in docs):
                    allowed = True
                    break

        if not allowed:
            raise PermissionError("You do not have permission to download this document.")
            
        file_path = os.path.join(os.path.dirname(__file__), "..", "static", "docs", f"{doc_id}.pdf")
        file_path = os.path.normpath(file_path)
        
        if not os.path.exists(file_path):
            raise ValueError("PDF file not found on server.")
            
        return file_path
