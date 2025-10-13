from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"))
    mime_type = Column(String)
    external_id = Column(String)
    last_fetched = Column(DateTime)

    # Relationships
    department = relationship("Department", back_populates="documents")
