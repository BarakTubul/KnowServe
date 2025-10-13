from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from app.core.database import Base


class MonitorLog(Base):
    __tablename__ = "monitor_log"

    id = Column(Integer, primary_key=True, index=True)
    query_id = Column(Integer, ForeignKey("chat_history.id"))
    valid = Column(Boolean, default=False)
    reason = Column(String)
    created_at = Column(DateTime)
