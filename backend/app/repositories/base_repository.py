# app/repositories/base_repository.py
from typing import Type, TypeVar, Generic, List, Optional
from sqlalchemy.orm import Session

T = TypeVar("T")  # SQLAlchemy model type

class BaseRepository(Generic[T]):
    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model

    def get(self, entity_id: int) -> Optional[T]:
        return (
            self.session.query(self.model)
            .filter(self.model.id == entity_id)
            .first()
        )

    def get_all(self) -> List[T]:
        return self.session.query(self.model).all()

    def delete(self, entity: T):
        self.session.delete(entity)

    def save(self, entity: T) -> T:
        # merge() acts as add-or-update
        return self.session.merge(entity)
