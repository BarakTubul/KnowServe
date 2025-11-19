# app/repositories/user_repository.py

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: Session):
        super().__init__(session, User)

    def get_by_email(self, email: str):
        return self.session.query(User).filter(User.email == email).first()

    def get_admin(self):
        return self.session.query(User).filter(User.role == UserRole.ADMIN).first()

    def get_manager_for_department(self, department_id: int):
        return (
            self.session.query(User)
            .filter(
                User.role == UserRole.MANAGER,
                User.department_id == department_id
            )
            .first()
        )

    
