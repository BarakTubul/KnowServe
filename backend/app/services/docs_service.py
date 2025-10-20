# app/services/docs_service.py
from app.models.document import Document
from app.models.department import Department
from app.core.database import SessionLocal

class DocsService:
    """Handles creation, retrieval and update of documents."""

    @staticmethod
    def list_all() -> list[dict]:
        """Return all documents with their linked departments."""
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
        return result


    @staticmethod
    def list_allowed(department_id: int) -> list[dict]:
        """Return documents accessible to a specific department."""
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
        return result


    @staticmethod
    def add_document(title: str, source_url: str, department_ids: list[int]):
        """Create a new document and assign it to one or more departments."""
        db = SessionLocal()
        departments = db.query(Department).filter(Department.id.in_(department_ids)).all()

        if not departments:
            db.close()
            raise ValueError("No valid departments found for the provided IDs.")

        new_doc = Document(title=title, source_url=source_url)
        new_doc.departments.extend(departments)

        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        db.close()
        return new_doc


    @staticmethod
    def update_permissions(doc_id: int, department_ids: list[int]):
        """Update which departments have access to the document."""
        db = SessionLocal()
        doc = db.query(Document).get(doc_id)
        if not doc:
            db.close()
            raise ValueError("Document not found.")

        departments = db.query(Department).filter(Department.id.in_(department_ids)).all()
        doc.departments = departments  # Replace current links
        db.commit()
        db.refresh(doc)
        db.close()
        return {"message": "Permissions updated.", "departments": [d.name for d in departments]}


    @staticmethod
    def delete_document(doc_id: int):
        """Delete a document."""
        db = SessionLocal()
        doc = db.query(Document).get(doc_id)
        if not doc:
            db.close()
            raise ValueError("Document not found.")
        db.delete(doc)
        db.commit()
        db.close()
        return {"message": f"Document {doc_id} deleted successfully."}
