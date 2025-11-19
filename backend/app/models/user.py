from sqlalchemy import Column, Integer, String, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from enum import Enum

class UserRole(Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(SqlEnum(UserRole), nullable=False, default=UserRole.EMPLOYEE)
    department_id = Column(Integer, ForeignKey("departments.id"))

    # Relationships
    department = relationship("Department", back_populates="users")
    chat_history = relationship("ChatHistory", back_populates="user")
