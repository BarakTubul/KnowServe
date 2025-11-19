# app/repositories/document_repository.py
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: Session):
        super().__init__(session, Document)

    def get_by_department(self, department_id: int):
        return (
            self.session.query(Document)
                .join(Document.departments)
                .filter(Department.id == department_id)
                .all()
        )

    def set_departments(self, doc_id: int, department_ids: list[int]):
        doc = self.get(doc_id)
        if not doc:
            return None
        deps = (
            self.session.query(Department)
                .filter(Department.id.in_(department_ids))
                .all()
        )
        doc.departments = deps
        return doc   # UnitOfWork will commit
