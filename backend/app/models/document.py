from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.department_documents import DepartmentDocument

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    source_url = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True)

    # Many-to-many relationship to Department
    departments = relationship(
        "Department",
        secondary="department_documents",
        back_populates="documents",
        lazy="joined"
    )
