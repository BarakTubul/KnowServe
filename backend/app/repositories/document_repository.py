# app/repositories/document_repository.py
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DocumentRepository(BaseRepository[Document]):
    def __init__(self):
        super().__init__(Document)

    def get_by_department(self, db: Session, department_id: int):
        return (
            db.query(Document)
              .join(Document.departments)
              .filter(Department.id == department_id)
              .all()
        )

    def set_departments(self, db: Session, doc_id: int, department_ids: list[int]):
        doc = db.query(Document).get(doc_id)
        if not doc:
            return None

        departments = db.query(Department).filter(Department.id.in_(department_ids)).all()
        doc.departments = departments
        db.commit()
        db.refresh(doc)
        return doc
