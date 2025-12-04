from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.department_documents_access import DepartmentDocumentAccess


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"))

    organization = relationship("Organization", back_populates="departments")

    # Many-to-many with Document
    documents = relationship(
        "Document",
        secondary="department_documents_access",
        back_populates="departments"
    )

    # 🔗 One-to-many: Department → Users
    users = relationship("User", back_populates="department")
