from sqlalchemy import Column, Integer, String
from app.core.database import Base
from sqlalchemy.orm import relationship


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    # Relationships
    departments = relationship("Department", back_populates="organization")
