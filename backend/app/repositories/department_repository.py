# app/repositories/department_repository.py
from sqlalchemy.orm import Session
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DepartmentRepository(BaseRepository[Department]):
    def __init__(self):
        super().__init__(Department)

    def get_documents(self, db: Session, department_id: int):
        dept = db.query(Department).get(department_id)
        return dept.documents if dept else []
