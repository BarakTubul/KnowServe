# app/repositories/base_repository.py
from typing import Type, TypeVar, Generic, List, Optional
from sqlalchemy.orm import Session

T = TypeVar("T")  # SQLAlchemy model type

class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T]):
        self.model = model

    def get(self, db: Session, id: int) -> Optional[T]:
        return db.query(self.model).get(id)

    def get_all(self, db: Session) -> List[T]:
        return db.query(self.model).all()

    def create(self, db: Session, obj: T) -> T:
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def delete(self, db: Session, id: int) -> bool:
        obj = db.query(self.model).get(id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True

    def update(self, db: Session, id: int, data: dict) -> Optional[T]:
        obj = db.query(self.model).get(id)
        if not obj:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        return obj
