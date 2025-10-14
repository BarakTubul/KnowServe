from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    query = Column(String, nullable=False)
    response = Column(String)
    created_at = Column(DateTime)
    semantic_vector = Column(String)
    source_doc = Column(String)

    # Relationships
    user = relationship("User", back_populates="chat_history")
