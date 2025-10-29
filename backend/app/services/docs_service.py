from app.models.document import Document
from app.models.department import Department
from app.core.database import SessionLocal
from app.core import redis_client
import asyncio
from app.external_api.google_drive.google_drive_client import GoogleDriveClient
from fastapi import UploadFile
from typing import List




class DocsService:
    """Handles creation, retrieval and update of documents with caching."""

    # -------------------------------------------------------------
    # 🔹 List all documents (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_all() -> list[dict]:
        """Return all documents with their linked departments."""
        cache_key = "docs:all"
        cached = await redis_client.get_cache(cache_key)
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
                "departments": [dep.name for dep in d.departments],
                "is_active": d.is_active,
            }
            for d in docs
        ]
        db.close()

        await redis_client.set_cache(cache_key, result, expire_seconds=600)
        print("💾 [Redis] Cache set for list_all()")
        return result

    # -------------------------------------------------------------
    # 🔹 List documents allowed for a department (cached)
    # -------------------------------------------------------------
    @staticmethod
    async def list_allowed(department_id: int) -> list[dict]:
        """Return documents accessible to a specific department."""
        cache_key = f"docs:department:{department_id}"
        cached = await redis_client.get_cache(cache_key)
        if cached:
            print(f"✅ [Redis] Cache hit for department {department_id}")
            return cached

        db = SessionLocal()
        dept = db.query(Department).get(department_id)
        if not dept:
            db.close()
            return []

        result = [
            {"id": d.id, "title": d.title, "source_url": d.source_url}
            for d in dept.documents
        ]
        db.close()

        await redis_client.set_cache(cache_key, result, expire_seconds=900)
        print(f"💾 [Redis] Cache set for department {department_id}")
        return result

  

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

        departments = db.query(Department).filter(Department.id.in_(department_ids)).all()
        doc.departments = departments
        db.commit()
        db.refresh(doc)
        db.close()

        # 🔄 Invalidate caches
        from app.core.redis_client import redis_client
        if redis_client:
            await redis_client.delete("docs:all")
            for dep_id in department_ids:
                await redis_client.delete(f"docs:department:{dep_id}")
            print("🧹 [Redis] Invalidated caches after update_permissions()")

        return {"message": "Permissions updated.", "departments": [d.name for d in departments]}

       # -------------------------------------------------------------
    # 🔹 Upload multiple documents to Google Drive and DB
    # -------------------------------------------------------------
    @staticmethod
    async def upload_multiple(
        files: List[UploadFile],
        names: List[str],
        department_ids: List[int],
    ):
        """
        Upload multiple files, store them in the correct department folders (Google Drive),
        and add metadata to the database.

        Parameters:
            files: Uploaded file objects.
            names: List of document names matching the files.
            department_ids: Department IDs that own the uploaded documents.
        """
        uploaded_docs = []
        db = SessionLocal()

        try:
            # ✅ Fetch departments (ownership)
            departments = (
                db.query(Department).filter(Department.id.in_(department_ids)).all()
            )
            if not departments:
                raise ValueError("No valid departments found for the provided IDs.")

            # 🔹 Upload and save each document
            for file, name in zip(files, names):
                # Determine department folder (first department)
                department_name = departments[0].name
                drive_client = GoogleDriveClient(department_name)
                
                # Upload file to Google Drive
                uploaded = await drive_client.upload_file(file)

                # Save metadata to DB
                new_doc = Document(
                    title=name,
                    source_url=uploaded["url"],
                    file_id=uploaded["file_id"],  # Drive file ID
                    is_active=True,
                )
                new_doc.departments.extend(departments)
                db.add(new_doc)
                db.commit()
                db.refresh(new_doc)

                uploaded_docs.append(
                    {
                        "id": new_doc.id,
                        "title": new_doc.title,
                        "source_url": new_doc.source_url,
                    }
                )

            # 🔄 Invalidate Redis cache
            from app.core.redis_client import redis_client
            if redis_client:
                await redis_client.delete("docs:all")
                for dep_id in department_ids:
                    await redis_client.delete(f"docs:department:{dep_id}")
                print("🧹 [Redis] Invalidated caches after upload_multiple()")

            print(f"✅ [DocsService] Uploaded {len(uploaded_docs)} document(s).")
            return uploaded_docs

        except Exception as e:
            db.rollback()
            print(f"❌ [DocsService] Upload failed: {e}")
            raise
        finally:
            db.close()
        

    # -------------------------------------------------------------
    # 🔹 Delete multiple documents from Drive and DB
    # -------------------------------------------------------------
    @staticmethod
    async def delete_multiple(doc_ids: list[int]):
        """
        Delete multiple documents from DB and their Drive folders.
        Each document’s file_id (if exists) will be deleted from Drive.
        """
        db = SessionLocal()
        deleted_docs = []
        try:
            docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
            if not docs:
                raise ValueError("No documents found for the provided IDs.")

            for doc in docs:
                department_name = doc.departments[0].name if doc.departments else None

                # 🔹 Delete from Drive if applicable
                if getattr(doc, "file_id", None) and department_name:
                    try:
                        drive_client = google_drive_client(department_name)
                        drive_client.delete_file(doc.file_id)
                        print(f"🗑️ [Drive] Deleted file {doc.file_id}")
                    except Exception as e:
                        print(f"⚠️ [Drive] Could not delete file {doc.file_id}: {e}")

                deleted_docs.append({"id": doc.id, "title": doc.title})
                db.delete(doc)

            db.commit()

            # 🔄 Invalidate Redis caches
            
            await redis_client.delete("docs:all")
            print("🧹 [Redis] Invalidated caches after delete_multiple()")

            print(f"✅ [DocsService] Deleted {len(deleted_docs)} document(s).")
            return {
                "message": f"{len(deleted_docs)} document(s) deleted successfully.",
                "deleted": deleted_docs,
            }

        except Exception as e:
            db.rollback()
            print(f"❌ [DocsService] Deletion failed: {e}")
            raise
        finally:
            db.close()
