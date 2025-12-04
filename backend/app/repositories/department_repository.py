# app/repositories/department_repository.py
from sqlalchemy.orm import Session
from app.models.department import Department
from app.repositories.base_repository import BaseRepository

class DepartmentRepository(BaseRepository[Department]):
    def __init__(self, session: Session):
        super().__init__(session, Department)

    def get_accessible_documents(self, department_id: int):
        """Documents this department has access to."""
        dept = self.get(department_id)
        return dept.documents if dept else []

    def get_owned_documents(self, department_id: int):
        """Documents owned/created by this department."""
        dept = self.get(department_id)
        return dept.owned_documents if dept else []


