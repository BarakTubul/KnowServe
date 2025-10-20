# app/models/department_documents.py
from sqlalchemy import Column, Integer, ForeignKey, Table
from app.core.database import Base

# Association table between Departments and Documents
class DepartmentDocument(Base):
    __tablename__ = "department_documents"

    department_id = Column(Integer, ForeignKey("departments.id"), primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), primary_key=True)
