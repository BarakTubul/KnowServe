# app/core/unit_of_work.py
from contextlib import AbstractContextManager
from app.core.database import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.user_repository import UserRepository

class UnitOfWork(AbstractContextManager):
    def __init__(self):
        self.session = None
        self.documents = None
        self.departments = None

    def __enter__(self):
        self.session = SessionLocal()

        # Attach repositories
        self.documents = DocumentRepository(self.session)
        self.departments = DepartmentRepository(self.session)
        self.users = UserRepository(self.session)

        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.session.commit()
        else:
            self.session.rollback()

        self.session.close()
