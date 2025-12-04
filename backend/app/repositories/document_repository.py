# app/repositories/document_repository.py
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: Session):
        super().__init__(session, Document)

    # -----------------------------------------
    # ACCESS (many-to-many)
    # -----------------------------------------
    def get_documents_with_access_for_department(self, department_id: int):
        """Documents that a department is allowed to access."""
        return (
            self.session.query(Document)
                .join(Document.departments)
                .filter(Department.id == department_id)
                .all()
        )

    # -----------------------------------------
    # OWNERSHIP (one-to-many)
    # -----------------------------------------
    def get_documents_owned_by_department(self, department_id: int):
        """Documents that originated from / are owned by the department."""
        return (
            self.session.query(Document)
                .filter(Document.owner_department_id == department_id)
                .all()
        )

    # -----------------------------------------
    # MODIFY ACCESS
    # -----------------------------------------
    def set_document_access(self, doc_id: int, department_ids: list[int]):
        """Set which departments may access this document."""
        doc = self.get(doc_id)
        if not doc:
            return None

        deps = (
            self.session.query(Department)
                .filter(Department.id.in_(department_ids))
                .all()
        )

        doc.departments = deps
        return doc
