from sqlalchemy import Column, Integer, String, Boolean,ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.department_documents_access import DepartmentDocumentAccess


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    source_url = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True)
    status = Column(String(255), nullable=False)

    # NEW
    owner_department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    owner_department = relationship("Department", backref="owned_documents")

    # Existing many-to-many
    departments = relationship(
        "Department",
        secondary="department_documents_access",
        back_populates="documents",
        lazy="joined",
    )
