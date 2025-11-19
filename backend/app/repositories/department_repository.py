# app/repositories/department_repository.py
from sqlalchemy.orm import Session
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DepartmentRepository(BaseRepository[Department]):
    def __init__(self, session: Session):
        super().__init__(session, Department)

    def get_documents(self, department_id: int):
        dept = self.get(department_id)
        return dept.documents if dept else []

