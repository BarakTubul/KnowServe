# app/services/auth_service.py
from app.core.unit_of_work import UnitOfWork
from app.models.user import UserRole,User
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt import create_access_token


class AuthService:

    # ----------------------------
    # REGISTER USER
    # ----------------------------
    @staticmethod
    def register(name: str, email: str, password: str, role: str, department_id: int):
        # role = role.lower()
        role_enum = UserRole(role)

        with UnitOfWork() as uow:

            # 1️⃣ Check if email exists
            if uow.users.get_by_email(email):
                raise ValueError("Email already registered.")

            # 2️⃣ Only ONE admin allowed
            if role_enum == UserRole.ADMIN:
                if uow.users.get_admin():
                    raise PermissionError("Admin already exists.")

            # 3️⃣ Only ONE manager per department
            if role_enum == UserRole.MANAGER:
                if uow.users.get_manager_for_department(department_id):
                    raise PermissionError("This department already has a manager.")

            # 4️⃣ Hash password
            hashed = hash_password(password)

            # 5️⃣ Create the user
            user = User(
                name=name.strip(),
                email=email.lower(),
                password_hash=hashed,
                role=role_enum,
                department_id=department_id,
            )

            uow.users.save(user)
        

        return {"message": "User registered successfully"}

    # ----------------------------
    # LOGIN USER
    # ----------------------------
    @staticmethod
    def login(email: str, password: str):
        with UnitOfWork() as uow:
            user = uow.users.get_by_email(email)

            if not user:
                raise ValueError("Invalid email or password.")

            if not verify_password(password, user.password_hash):
                raise ValueError("Invalid email or password.")

            # 🟢 Extract user data BEFORE session closes
            user_data = {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "department_id": user.department_id,
            }

            token = create_access_token(
                {
                    "user_id": user_data["id"],
                    "role": user_data["role"],
                    "department_id": user_data["department_id"],
                }
            )

        # 🟢 Now safe to return (no ORM object outside UoW)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_data,
        }
